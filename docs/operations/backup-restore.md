# Backup and Restore

## What has to be backed up, and why both halves

State lives in two places that refer to each other.

| Half | Holds | Lost alone means |
|---|---|---|
| PostgreSQL | document rows, analyses, reviews, the audit trail, the job queue | a directory of images with no extraction, no review, no audit trail |
| Managed document storage | the document bytes | a catalogue of documents nobody can open |
| Pending upload storage | bytes of accepted-but-unprocessed uploads | queued jobs that fail when a worker claims them |

There is **no `storage_path` column**. The `documents` table holds an id
and the path is derived from it:

```
<DOCUMENT_STORAGE_DIR>/<document id>/original.<ext>
```

So the two halves are joined by the id, and a restore that puts the
files anywhere else produces rows pointing at nothing.

## The commands

```
# everything, weekly, from a scheduler
python scripts/maintenance/backup.py --output /backups --all

# verify a backup without touching anything
python scripts/maintenance/restore.py --input /backups/vigilox-backup-20260821T020000Z --all

# actually restore
python scripts/maintenance/restore.py --input /backups/vigilox-backup-20260821T020000Z --all --confirm
```

`--confirm` is required to write anything. Without it the restore
verifies every checksum, checks every precondition, and stops. Use it as
the routine "is my backup good" check — it is the only check that means
anything.

## Credentials

The scripts contain none, build none into a command line, and write none
into the manifest.

The URL comes from `DATABASE_URL`. The password reaches `pg_dump` and
`pg_restore` through `PGPASSWORD` in the child process environment only —
never as an argument, because arguments are readable by every user on the
host through `ps`. Everything printed and everything written to the
manifest passes through redaction, so the manifest records *which*
database a backup came from without recording how to connect to it.

Do not put a password in `--label`. It goes in the manifest verbatim.

## The consistency problem, stated plainly

**A `pg_dump` and a `tar` are two operations at two different instants.
They are not a transactionally consistent pair, and no scripting makes
them one.** Anything created or deleted between them exists in one half
and not the other.

There are two honest positions and the manifest always records which one
you took.

### Quiesced — the consistent one

```
1. stop accepting uploads      (scale the proxy's upstream to zero, or
                                return 503 for POST /api/v1/document-jobs)
2. stop the worker             docker compose stop worker
3. wait for PROCESSING to hit 0    GET /health/workers
4. python scripts/maintenance/backup.py --output /backups --all --quiesced
5. start the worker, resume uploads
```

Nothing is being created or deleted, so the halves cannot disagree.

`--quiesced` is recorded as **a claim the operator made**. The script
cannot prove that no other process is about to write — nothing running in
one process can — so it does not pretend to. What it does do is look for
evidence against the claim, and refuse if it finds any: a worker still
checking in, or a job still `PROCESSING`. A backup labelled consistent
that is not consistent is worse than one labelled hot, because the label
is what gets trusted at 3am.

Budget the window from measured behaviour: OCR runs a 28s median and 43s
maximum per document, so a worker mid-document finishes in well under a
minute. The dump itself is small — the database holds rows, not images.

### Hot — the reconcilable one

Drop `--quiesced`. The backup runs against a live service, the manifest
says `"consistency": "hot"`, and you accept a small, bounded
disagreement.

**The order is deliberate: database first, then the filesystem.** This is
the whole reason the backup is a script rather than two lines in a
runbook.

With the database captured at T1 and the files at T2:

| Concurrent event | Result on restore | Recoverable? |
|---|---|---|
| An upload at T1.5 | file present, no row → **orphan file** | Yes — `reconcile_storage.py` classifies and clears orphans |
| A deletion at T1.5 | row present, no file → **missing storage** | No — the bytes are gone |

Reverse the order and you swap which one you get. Uploads happen
continuously and are the product working; deletions are rare,
administrative and deliberate. So database-first makes the *common*
concurrent event fail in the direction reconciliation can fix.

After any hot restore:

```
python scripts/maintenance/reconcile_storage.py          # dry run, the default
```

A few orphans are expected and are the designed failure direction. A row
with **missing** storage is not, and needs investigating before the
service takes traffic.

## Pending uploads are a separate archive

`pending.tar.gz`, never mixed into `documents.tar.gz`.

Phase 9.2 keeps the pending root outside managed storage because a
pending file has no document row by definition — the integrity scan would
class every in-flight upload as an orphan, and orphans are the one class
reconciliation deletes on its own. One combined archive would put that
invariant one careless extraction away from being undone.

The restore refuses outright if the two roots overlap, before writing
anything.

They matter because **the dump contains the job queue.** Restore
`QUEUED` and `RETRY_WAIT` jobs without their sources and a worker claims
each one, cannot find its file, and fails it — which looks like a batch
of bad documents rather than an incomplete restore. Both scripts warn
when the dump has unfinished jobs and the pending archive is absent.

## What the restore refuses, and why

| Refusal | Override | Why it is there |
|---|---|---|
| No `--confirm` | — | A restore tool whose default action is to restore gets run by accident exactly once |
| Manifest says `complete=false` | none | An incomplete backup is kept for inspection, not for restoring |
| A checksum does not match | none | Verification runs *before* extraction so a damaged archive cannot leave the target holding half a backup |
| The target database has tables | `--force` | Restoring into a populated database means dropping what is in it |
| The target document tree is non-empty | `--force` | Merging two sets of documents produces neither |
| The pending and managed roots overlap | none | Phase 9.2 — it would stage every pending upload for automatic deletion |
| The dump's Alembic revision ≠ the code's head | none | Restoring an older dump under newer code presents as confusing query errors hours later, not as a restore problem |
| An archive member escapes the destination | none | An archive is untrusted input, and a matching checksum only proves it is the archive the manifest describes — the manifest being a JSON file anybody can write |

`--force` overrides two of these. Read the refusal before using it.

The database restore runs in `--single-transaction` with
`--exit-on-error`: it lands whole or not at all. Without
`--exit-on-error`, `pg_restore` continues past errors and exits 0, which
is how a restore that quietly dropped a constraint is discovered weeks
later.

## In containers

`pg_dump` is not in the application image, deliberately: it is an
operator tool, and putting a database client in every API replica for
something that runs weekly is the wrong place for it. The `postgres`
service image already has a **version-matched** client, which matters —
a `pg_dump` older than the server refuses to run, and a newer one
produces an archive the older `pg_restore` cannot read.

```
# database only, from the postgres service
docker compose exec -T postgres \
  pg_dump -Fc -U vigilox -d vigilox_document_intelligence \
  > /backups/database.dump

# the document volumes, from a throwaway container
docker compose run --rm \
  -v vigilox_documents:/data/documents:ro \
  -v /backups:/out \
  postgres tar czf /out/documents.tar.gz -C /data/documents .
```

To use the scripts unchanged instead, run them where a client is
available and point `VIGILOX_PG_BIN` at it:

```
VIGILOX_PG_BIN=/usr/lib/postgresql/18/bin \
  python scripts/maintenance/backup.py --output /backups --all
```

On Windows the scripts find an installed client that is not on `PATH`
(`C:\Program Files\PostgreSQL\<version>\bin`) without being told.

## What is NOT backed up, on purpose

| Not included | Why |
|---|---|
| `.env`, `GROQ_API_KEY`, the database password | Secrets belong in a secret store. A backup gets copied to object storage, a laptop, a ticket attachment |
| The PaddleOCR model cache | Baked into the image at build time. Restoring it would restore a stale copy over a correct one |
| Container logs | The log destination's own retention handles these |
| The application image | The registry has it, tagged |

## Restore, end to end

```
1. Provision an empty database and an empty document volume.
2. Deploy the code revision the manifest names.
       the manifest records the Alembic revision; the restore
       refuses a mismatch rather than producing a database the
       application cannot read
3. Verify first, write nothing:
       python scripts/maintenance/restore.py --input <dir> --all
4. Restore:
       python scripts/maintenance/restore.py --input <dir> --all --confirm
5. Check the halves agree:
       python scripts/maintenance/reconcile_storage.py          # dry run, the default
6. Start the API. Check GET /health/ready.
7. Start the worker. Check GET /health/workers.
8. Deal with the requeued unfinished jobs -- fail them
   deliberately if their sources were not in the backup.
9. Return traffic.
```

## Testing the restore

`tests/deployment/test_phase11_backup_restore.py` performs the full round
trip on **synthetic data only**: a throwaway database
(`vigilox_backup_test`, dropped afterwards), synthetic PNG bytes, and
temporary storage roots. It deletes the originals before restoring —
otherwise every assertion afterwards would pass against data that was
never removed — and then asserts the pairing by running the
application's own `StorageIntegrityService` against the result rather
than by re-deriving where the files ought to be.

Its first test proves the redirection took effect before anything else
runs. Without that, a suite that failed to redirect would be a
destructive operation on live documents that reports PASS.

Run the restore test on a schedule, not once. A backup script that has
never been restored from is a directory of files believed to be a backup,
and the belief is checked exactly once.
