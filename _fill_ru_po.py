"""Fill locale/ru/LC_MESSAGES/django.po: set msgstr = msgid for empty entries."""
import polib

po = polib.pofile(r'd:\cargo\InterCargoWeb\locale\ru\LC_MESSAGES\django.po', encoding='utf-8')
filled = 0
for entry in po:
    if not entry.msgstr and entry.msgid:
        entry.msgstr = entry.msgid
        filled += 1
po.save()
print(f'Filled {filled} entries in ru/django.po')
