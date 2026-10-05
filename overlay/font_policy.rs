//! Conservative embedding policy, not proof of a font's provenance or complete license rights.
//! OpenType OS/2 fsType: only installable (0) or editable (8), with subsetting allowed.

pub fn permits_subset_embedding(fs_type: Option<u16>) -> bool {
    matches!(fs_type, Some(0) | Some(8))
}

fn u16_at(data: &[u8], at: usize) -> Option<u16> {
    Some(u16::from_be_bytes(data.get(at..at.checked_add(2)?)?.try_into().ok()?))
}
fn u32_at(data: &[u8], at: usize) -> Option<u32> {
    Some(u32::from_be_bytes(data.get(at..at.checked_add(4)?)?.try_into().ok()?))
}

pub fn embedding_flags(data: &[u8], face_index: u32) -> Option<u16> {
    let offset = if data.get(..4)? == b"ttcf" {
        let count = u32_at(data, 8)?;
        if face_index >= count { return None; }
        usize::try_from(u32_at(data, 12usize.checked_add(usize::try_from(face_index).ok()?.checked_mul(4)?)?)?).ok()?
    } else {
        if face_index != 0 { return None; }
        0
    };
    let signature = data.get(offset..offset.checked_add(4)?)?;
    if signature != b"\x00\x01\x00\x00" && signature != b"OTTO" && signature != b"true" { return None; }
    let count = usize::from(u16_at(data, offset.checked_add(4)?)?);
    let directory = offset.checked_add(12)?;
    data.get(directory..directory.checked_add(count.checked_mul(16)?)?)?;
    let mut flags = None;
    for n in 0..count {
        let table = directory.checked_add(n.checked_mul(16)?)?;
        if data.get(table..table.checked_add(4)?)? != b"OS/2" { continue; }
        if flags.is_some() { return None; }
        let start = usize::try_from(u32_at(data, table.checked_add(8)?)?).ok()?;
        let len = usize::try_from(u32_at(data, table.checked_add(12)?)?).ok()?;
        if len < 10 { return None; }
        data.get(start..start.checked_add(len)?)?;
        flags = Some(u16_at(data, start.checked_add(8)?)?);
    }
    flags
}

#[cfg(test)]
mod tests {
    use super::*;
    fn synthetic_sfnt(flags: u16) -> Vec<u8> {
        // Metadata-only test buffer, not a usable font.
        let mut data=vec![0;38];
        data[..4].copy_from_slice(b"\x00\x01\x00\x00");
        data[4..6].copy_from_slice(&1u16.to_be_bytes());
        data[12..16].copy_from_slice(b"OS/2");
        data[20..24].copy_from_slice(&28u32.to_be_bytes());
        data[24..28].copy_from_slice(&10u32.to_be_bytes());
        data[36..38].copy_from_slice(&flags.to_be_bytes());
        data
    }
    #[test] fn valid_flags_are_read() {
        for flags in [0,2,4,8,0x100,0x200] { assert_eq!(embedding_flags(&synthetic_sfnt(flags),0),Some(flags)); }
    }
    #[test] fn restriction_and_unknown_flags_fail_closed() {
        for flags in [None,Some(2),Some(4),Some(6),Some(12),Some(0x100),Some(0x108),Some(0x200),Some(0xffff)] {
            assert!(!permits_subset_embedding(flags));
        }
        assert!(permits_subset_embedding(Some(0))); assert!(permits_subset_embedding(Some(8)));
    }
    #[test] fn truncation_fails_closed() {
        let data=synthetic_sfnt(8);
        for end in 0..data.len() { assert_eq!(embedding_flags(&data[..end],0),None); }
    }
    #[test] fn out_of_range_face_or_offset_fails_closed() {
        let mut data=synthetic_sfnt(8);
        assert_eq!(embedding_flags(&data,1),None);
        data[20..24].copy_from_slice(&u32::MAX.to_be_bytes());
        assert_eq!(embedding_flags(&data,0),None);
    }
    #[test] fn collection_uses_absolute_table_offsets() {
        let mut collection=vec![0;16];
        collection[..4].copy_from_slice(b"ttcf");
        collection[8..12].copy_from_slice(&1u32.to_be_bytes());
        collection[12..16].copy_from_slice(&16u32.to_be_bytes());
        let mut face=synthetic_sfnt(8);
        face[20..24].copy_from_slice(&44u32.to_be_bytes());
        collection.extend(face);
        assert_eq!(embedding_flags(&collection,0),Some(8));
        assert_eq!(embedding_flags(&collection,1),None);
    }
    #[test] fn unsupported_container_rejected() {
        let mut data=synthetic_sfnt(0); data[..4].copy_from_slice(b"wOF2");
        assert_eq!(embedding_flags(&data,0),None);
    }
}
