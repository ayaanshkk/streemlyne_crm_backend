"""
Run this from your backend folder:
python fix_interior_models.py
"""

filepath = 'models/modules/interior_design.py'

with open(filepath, encoding='utf-8') as f:
    lines = f.readlines()

fixed = []
skipped = []

for i, line in enumerate(lines, 1):
    if ("db.relationship('Customer'" in line or
        'db.relationship("Customer"' in line or
        "db.relationship('Tenant'" in line or
        'db.relationship("Tenant"' in line):
        # Comment out instead of delete so it's reversible
        fixed.append('    # TEMP DISABLED: ' + line.lstrip())
        skipped.append(f'Line {i}: {line.rstrip()}')
    else:
        fixed.append(line)

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(fixed)

print(f'Done! Commented out {len(skipped)} relationship lines:')
for s in skipped:
    print(f'  {s}')