"""Only reviewed, owned native preview controls may change synthetic print media."""
VALUES={'Paper size':frozenset({'Letter','A4'}),'Margins':frozenset({'Default','None','Minimum','Custom'})}
def dropdown_index(nodes,label,pids):
    if label not in VALUES:raise ValueError('Unknown preview setting')
    matches=[]
    for i,n in enumerate(nodes):
        if n.get('pid') not in pids or n.get('enabled') is not True:continue
        old=n.get('type')=='Button' and n.get('name') in {label+' '+v for v in VALUES[label]}
        new=n.get('type')=='ComboBox' and n.get('group')==label
        if old or new:matches.append(i)
    if len(matches)>1:raise ValueError('Ambiguous preview dropdown')
    return matches[0] if matches else None

def option_index(nodes,value,pids):
    if value not in ('A4','None'):raise ValueError('Unreviewed print option')
    matches=[i for i,n in enumerate(nodes) if n.get('pid') in pids and n.get('enabled') is True
             and n.get('type')=='ListItem' and n.get('name')==value]
    if len(matches)>1:raise ValueError('Ambiguous preview option')
    return matches[0] if matches else None

def validate_settings(observed):
    if observed.get('paper')!='A4' or observed.get('margins')!='None' or observed.get('actualSize') is not True:
        raise ValueError('Preview must use A4, no extra margins and actual size before the system print dialog')
