"""
Copy StreemLyne's reference data from the old database ("StreemLyne_MT")
into the shared database ("streemLyne_mt_dev2"), keeping the same IDs:
currencies, subscription plans, modules and plan-module links.

Only rows whose ID is not already in the target are added; nothing is
overwritten. Columns are matched by name.

Usage: python copy_streemlyne_reference_data.py --source <old DB URL> --target <new DB URL> [--dry-run]
Run 20261016_streemlyne_fai_on_dev2.sql again afterwards so ID numbering
continues after the copied IDs.
"""

import argparse
import sys

import psycopg2
import psycopg2.extras

TABLES = [  # (table, primary key) in dependency order
    ('Currency_Master', 'currency_id'),
    ('Subscription_Plans', 'subscription_id'),
    ('Module_Master', 'module_id'),
    ('Subscription_Module_Mapping', 'subscription_module_mapping_id'),
]


def columns(cur, schema, table):
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position""", (schema, table))
    return [r[0] for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True)
    ap.add_argument('--target', required=True)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    src = psycopg2.connect(a.source)
    src.set_session(readonly=True)
    dst = psycopg2.connect(a.target)
    try:
        with src.cursor() as sc, dst.cursor() as dc:
            for table, pk in TABLES:
                shared = [c for c in columns(sc, 'StreemLyne_MT', table) if c in set(columns(dc, 'streemLyne_mt_dev2', table))]
                sc.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in shared)} FROM "StreemLyne_MT"."{table}" ORDER BY "{pk}"')
                rows = sc.fetchall()
                added = 0
                for r in rows:
                    dc.execute(f'INSERT INTO "streemLyne_mt_dev2"."{table}" ({", ".join(chr(34) + c + chr(34) for c in shared)}) '
                               f'VALUES ({", ".join(["%s"] * len(shared))}) ON CONFLICT ("{pk}") DO NOTHING',
                               [psycopg2.extras.Json(v) if isinstance(v, (dict, list)) else v for v in r])
                    added += dc.rowcount
                print(f'  {table}: {added} added ({len(rows)} in source)')
        if a.dry_run:
            dst.rollback()
            print('DRY RUN - rolled back, nothing saved')
        else:
            dst.commit()
            print('COMMITTED')
    except Exception:
        dst.rollback()
        print('FAILED - rolled back, nothing saved', file=sys.stderr)
        raise
    finally:
        src.close()
        dst.close()


if __name__ == '__main__':
    main()
