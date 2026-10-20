# 08. Dry run and safe defaults

**In one line:** by default the tool only shows what it would do; it changes something only when
you explicitly say so.

## The idea

A "preview" before you print, or the "are you sure?" before you delete. The default should be the
choice that cannot do harm.

## Tiny example

```bash
python -m app sync abc123            # safe: prints "would_create", writes nothing
python -m app sync abc123 --apply    # deliberate: really creates the customer
```

## In OrderBridge

- [`sync_contact(..., dry_run=True)`](../../app/services/customer_sync.py) returns `would_create`
  and never calls the create method.
- [`app/cli.py`](../../app/cli.py) makes dry run the default; `--apply` turns writing on, and the
  first output line always states which mode is active.
- Only the `no_match` case may ever write. `matched`, `no_email` and `ambiguous` never do, even
  with `--apply`.
- A dry run was how the first live checks were done safely before any real write.

## Check yourself

*Why is dry run the default and writing the option?*

Model answer: a mistake or wrong ID in the default mode should show something, not change real
data; writing has to be a deliberate choice.
