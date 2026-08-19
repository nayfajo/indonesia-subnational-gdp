"""Temporary: remove wrong W2 entries from corrections log."""
import pandas as pd

log = pd.read_csv('pipeline_out/full_runs/corrections_log.csv')
print('Before:', len(log), 'rows')

df = pd.read_csv('pipeline_out/full_runs/csvs/PDRB-capita_2017-2019_wide_v2.csv')

keep_rows = []
for _, row in log.iterrows():
    if row['fix_id'] != 'W2':
        keep_rows.append(True)
    else:
        idx = int(row['row_index_kab'])
        keep_rows.append(df.loc[idx, 'province_name'] == 'LAMPUNG')

log_clean = log.loc[[k for k, v in zip(log.index, keep_rows) if v]]
removed = sum(1 for v in keep_rows if not v)
print(f'After: {len(log_clean)} rows (removed {removed} wrong W2 entries)')
log_clean.to_csv('pipeline_out/full_runs/corrections_log.csv', index=False)
print('Saved')
