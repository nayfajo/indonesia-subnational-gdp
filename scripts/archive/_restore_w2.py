"""Temporary: restore non-Lampung rows wrongly nulled by W2 fix."""
import pandas as pd

log = pd.read_csv('pipeline_out/full_runs/corrections_log.csv')
w2 = log[log['fix_id'] == 'W2'].copy()

df = pd.read_csv('pipeline_out/full_runs/csvs/PDRB-capita_2017-2019_wide_v2.csv')

restored = 0
for _, row in w2.iterrows():
    idx = int(row['row_index_kab'])
    province = df.loc[idx, 'province_name']
    if province != 'LAMPUNG':
        df.loc[idx, 'value'] = row['kab_value_before']
        restored += 1

print(f'Restored {restored} non-Lampung rows')
df.to_csv('pipeline_out/full_runs/csvs/PDRB-capita_2017-2019_wide_v2.csv', index=False)
print('Saved')

lamp = df[(df['province_name'] == 'LAMPUNG') & df['regency_code'].isin([71.0, 72.0])]
print('\nLampung 71/72 rows after restore:')
print(lamp[['province_name', 'region_name_raw', 'year', 'value']].to_string())
