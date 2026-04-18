"""Apply EN and KK translations to .po files. Run after all _trans_*.py parts."""
import polib, sys, importlib.util, os

def load_dict(path):
    spec = importlib.util.spec_from_file_location("mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.EN, mod.KK

def apply(po_path, trans_dict):
    po = polib.pofile(po_path, encoding='utf-8')
    filled = 0
    for entry in po:
        if entry.msgid in trans_dict:
            if not entry.msgstr or entry.msgstr == entry.msgid:
                entry.msgstr = trans_dict[entry.msgid]
                filled += 1
    po.save()
    return filled

parts_dir = os.path.dirname(os.path.abspath(__file__))
EN_all, KK_all = {}, {}

for fname in sorted(os.listdir(parts_dir)):
    if fname.startswith('_trans_part') and fname.endswith('.py'):
        path = os.path.join(parts_dir, fname)
        en, kk = load_dict(path)
        EN_all.update(en)
        KK_all.update(kk)

print(f'Loaded: {len(EN_all)} EN, {len(KK_all)} KK entries')

en_c = apply(r'd:\cargo\InterCargoWeb\locale\en\LC_MESSAGES\django.po', EN_all)
kk_c = apply(r'd:\cargo\InterCargoWeb\locale\kk\LC_MESSAGES\django.po', KK_all)
print(f'Filled: EN={en_c}, KK={kk_c}')
