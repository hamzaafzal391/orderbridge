# 09. Exit codes

**In one line:** a command ends with a number that tells other programs how it went, so they do not
have to read the printed text.

## The idea

A traffic light for scripts. People read sentences; scripts need something that never changes
wording.

## Tiny example

```bash
python -m app sync abc123
echo $?        # prints 0, 1, 2 or 3
```

| Code | Meaning in OrderBridge |
|---|---|
| 0 | matched, created, or would be created |
| 1 | needs a person: no email, ambiguous, or name conflict |
| 2 | bad usage (argparse's own code) |
| 3 | configuration problem or service error |

## In OrderBridge

- [`app/cli.py`](../../app/cli.py) chooses the code; the rules are in its top constants.
- A script can alert a person on `1`, retry later on `3`, and carry on at `0`.
- Errors go to stderr, results to stdout, so scripts can separate them.

## Check yourself

*Why use exit codes instead of only printed text?*

Model answer: automated jobs cannot reliably read sentences; a number is stable and tells them
whether to continue, alert someone or retry.
