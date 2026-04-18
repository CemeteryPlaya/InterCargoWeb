"""Force-apply Part 9 translations (including entries where msgstr == msgid)."""
import polib, importlib.util, os

def load_dict(path):
    spec = importlib.util.spec_from_file_location("mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.EN, mod.KK

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_trans_part9_fix.py')
EN, KK = load_dict(path)

base = r'd:\cargo\InterCargoWeb\locale'

for lang, trans in [('en', EN), ('kk', KK)]:
    po_path = os.path.join(base, lang, 'LC_MESSAGES', 'django.po')
    po = polib.pofile(po_path, encoding='utf-8')
    filled = 0
    for entry in po:
        if entry.msgid in trans and (not entry.msgstr or entry.msgstr == entry.msgid):
            entry.msgstr = trans[entry.msgid]
            filled += 1
    po.save()
    print(f'{lang}: force-filled {filled}')
