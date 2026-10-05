//! Keep inherited namespace bindings when header fragments are copied into a new XML root.
//! Prefixes are aliases, not schema identifiers; never rewrite text or QName attribute values.
use quick_xml::{events::Event, Reader, Writer};
use roxmltree::{Document, NodeId};
use std::ops::Range;

pub struct HeaderNamespaces<'a> {
    xml: &'a str,
    document: Document<'a>,
    elements: Vec<(usize, NodeId)>,
}

fn declared_by_writer(prefix: Option<&str>, uri: &str) -> bool {
    let expected = match prefix {
        Some("ha") => "http://www.hancom.co.kr/hwpml/2011/app",
        Some("hp") => "http://www.hancom.co.kr/hwpml/2011/paragraph",
        Some("hp10") => "http://www.hancom.co.kr/hwpml/2016/paragraph",
        Some("hs") => "http://www.hancom.co.kr/hwpml/2011/section",
        Some("hc") => "http://www.hancom.co.kr/hwpml/2011/core",
        Some("hh") => "http://www.hancom.co.kr/hwpml/2011/head",
        Some("hhs") => "http://www.hancom.co.kr/hwpml/2011/history",
        Some("hm") => "http://www.hancom.co.kr/hwpml/2011/master-page",
        Some("dc") => "http://purl.org/dc/elements/1.1/",
        Some("opf") => "http://www.idpf.org/2007/opf/",
        Some("epub") => "http://www.idpf.org/2007/ops",
        Some("ooxmlchart") => "http://www.hancom.co.kr/hwpml/2016/ooxmlchart",
        Some("hwpunitchar") => "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar",
        Some("hpf") => "http://www.hancom.co.kr/schema/2011/hpf",
        Some("config") => "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
        Some("xml") => "http://www.w3.org/XML/1998/namespace",
        _ => return false,
    };
    expected == uri
}

impl<'a> HeaderNamespaces<'a> {
    pub fn new(xml: &'a str) -> Result<Self, String> {
        let document = Document::parse(xml).map_err(|e| format!("header namespace validation: {e}"))?;
        let elements = document.descendants().filter(|n| n.is_element())
            .map(|n| (n.range().start, n.id())).collect();
        Ok(Self { xml, document, elements })
    }

    pub fn fragment(&self, range: Range<usize>) -> Result<String, String> {
        let original = self.xml.get(range.clone()).ok_or("Invalid XML fragment range")?;
        let mut output = String::with_capacity(original.len());
        let mut cursor = range.start;
        let first = self.elements.partition_point(|(start, _)| *start < range.start);
        for &(start, id) in &self.elements[first..] {
            if start >= range.end { break; }
            let node = self.document.get_node(id).ok_or("Missing XML node")?;
            if node.range().end > range.end { return Err("Partial XML element in fragment".into()); }
            if node.parent_element().is_some_and(|p| p.range().start >= range.start) { continue; }
            // Only fragment roots need inherited declarations. Descendant rebinding remains verbatim.
            let mut reader = Reader::from_str(&self.xml[start..range.end]);
            let event = reader.read_event().map_err(|e| e.to_string())?;
            let empty = matches!(event, Event::Empty(_));
            let mut tag = match event {
                Event::Start(e) | Event::Empty(e) => e.into_owned(),
                _ => return Err("XML fragment must begin at an element".into()),
            };
            let existing = tag.attributes().map(|a| a.map(|a| a.key.as_ref().to_vec()))
                .collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())?;
            let mut changed = false;
            for ns in node.namespaces() {
                if declared_by_writer(ns.name(), ns.uri()) { continue; }
                let name = ns.name().map_or_else(|| "xmlns".to_string(), |p| format!("xmlns:{p}"));
                if existing.iter().any(|a| a.as_slice() == name.as_bytes()) { continue; }
                // The string attribute conversion escapes exactly once.
                tag.push_attribute((name.as_str(), ns.uri()));
                changed = true;
            }
            if changed {
                let mut writer = Writer::new(Vec::new());
                writer.write_event(if empty { Event::Empty(tag) } else { Event::Start(tag) })
                    .map_err(|e| e.to_string())?;
                output.push_str(&self.xml[cursor..start]);
                output.push_str(&String::from_utf8(writer.into_inner()).map_err(|e| e.to_string())?);
                cursor = start + reader.buffer_position() as usize;
            }
        }
        output.push_str(&self.xml[cursor..range.end]);
        Ok(output)
    }

    pub fn memo_properties(&self) -> Result<Option<String>, String> {
        let root = self.document.root_element();
        let value = root.children().find(|n| n.is_element() && n.tag_name().name() == "refList" && n.tag_name().namespace() == root.tag_name().namespace())
            .and_then(|n| n.children().find(|c| c.is_element() && c.tag_name().name() == "memoProperties"));
        value.map(|n| self.fragment(n.range())).transpose()
    }

    pub fn tail(&self) -> Result<Option<String>, String> {
        let root = self.document.root_element();
        if root.tag_name().name() != "head" { return Ok(None); }
        let reference = root.children().find(|n| n.is_element() && n.tag_name().name() == "refList");
        let Some(reference) = reference else { return Ok(None); };
        let end = self.xml[..root.range().end].rfind("</").ok_or("Missing head closing tag")?;
        self.fragment(reference.range().end..end).map(Some)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const HEAD: &str = "http://www.hancom.co.kr/hwpml/2011/head";
    fn wrap(fragment: &str) -> String { format!("<hh:head xmlns:hh=\"{HEAD}\">{fragment}</hh:head>") }

    #[test]
    fn aliases_and_qname_values_survive_detachment() {
        let xml = format!(r#"<x:head xmlns:x="{HEAD}" xmlns:y="urn:ext"><x:refList><x:numbering><x:paraHead y:kind="x:Type">^1. &amp; 한글</x:paraHead></x:numbering></x:refList></x:head>"#);
        let ctx = HeaderNamespaces::new(&xml).unwrap();
        let start = xml.find("<x:paraHead").unwrap(); let end = xml.find("</x:numbering>").unwrap();
        let part = ctx.fragment(start..end).unwrap();
        let output = wrap(&part); let parsed = Document::parse(&output).unwrap();
        let node = parsed.descendants().find(|n| n.has_tag_name((HEAD, "paraHead"))).unwrap();
        assert_eq!(node.attribute(("urn:ext", "kind")), Some("x:Type"));
        assert_eq!(node.lookup_namespace_uri(Some("x")), Some(HEAD));
        assert_eq!(node.text(), Some("^1. & 한글"));
    }

    #[test]
    fn canonical_fragments_remain_byte_exact() {
        let part = r#"<hh:paraHead level="8" checkable="1">^8.</hh:paraHead>"#;
        let xml = wrap(part); let ctx = HeaderNamespaces::new(&xml).unwrap();
        let start = xml.find(part).unwrap();
        assert_eq!(ctx.fragment(start..start + part.len()).unwrap(), part);
    }

    #[test]
    fn inherited_default_namespace_is_preserved() {
        let xml = format!(r#"<head xmlns="{HEAD}"><refList><numbering><paraHead/></numbering></refList></head>"#);
        let ctx = HeaderNamespaces::new(&xml).unwrap();
        let start = xml.find("<paraHead").unwrap(); let end = xml.find("</numbering>").unwrap();
        let result = wrap(&ctx.fragment(start..end).unwrap());
        assert!(Document::parse(&result).unwrap().descendants().any(|n| n.has_tag_name((HEAD, "paraHead"))));
    }

    #[test]
    fn nested_bindings_and_local_declarations_are_not_duplicated() {
        let xml = r#"<root xmlns:x="urn:outer"><container xmlns:x="urn:inner"><x:item/><x:item xmlns:x="urn:local"><x:child/></x:item></container></root>"#;
        let ctx = HeaderNamespaces::new(xml).unwrap();
        let part = ctx.fragment(xml.find("<x:item").unwrap()..xml.find("</container>").unwrap()).unwrap();
        let result = wrap(&part); let parsed = Document::parse(&result).unwrap();
        let children: Vec<_> = parsed.root_element().children().filter(|n| n.is_element()).collect();
        assert_eq!(children[0].tag_name().namespace(), Some("urn:inner"));
        assert_eq!(children[1].tag_name().namespace(), Some("urn:local"));
        assert_eq!(part.matches("xmlns:x=\"urn:local\"").count(), 1);
    }

    #[test]
    fn rebinding_canonical_prefix_and_escaped_uri_are_preserved() {
        let xml = r#"<root xmlns:hh="urn:extension?a=1&amp;b=2"><hh:item value="hh:Type"/></root>"#;
        let ctx = HeaderNamespaces::new(xml).unwrap();
        let result = wrap(&ctx.fragment(xml.find("<hh:item").unwrap()..xml.find("</root>").unwrap()).unwrap());
        let parsed = Document::parse(&result).unwrap();
        assert!(parsed.descendants().any(|n| n.has_tag_name(("urn:extension?a=1&b=2", "item"))));
    }

    #[test]
    fn aliased_memo_and_tail_are_not_silently_dropped() {
        let xml = format!(r#"<x:head xmlns:x="{HEAD}" xmlns:e="urn:ext"><x:refList><x:memoProperties><e:item/></x:memoProperties></x:refList><!--keep--><x:docOption><e:setting value="yes"/></x:docOption></x:head>"#);
        let ctx = HeaderNamespaces::new(&xml).unwrap();
        for part in [ctx.memo_properties().unwrap().unwrap(), ctx.tail().unwrap().unwrap()] {
            Document::parse(&wrap(&part)).unwrap();
            assert!(part.contains("xmlns:e=\"urn:ext\""));
        }
        assert!(ctx.tail().unwrap().unwrap().contains("<!--keep-->"));
    }

    #[test]
    fn invalid_xml_and_partial_ranges_are_rejected() {
        assert!(HeaderNamespaces::new("<x:root/>").is_err());
        let ctx = HeaderNamespaces::new("<r><n>text</n></r>").unwrap();
        assert!(ctx.fragment(3..8).is_err());
        assert!(ctx.fragment(3..100).is_err());
    }
}
