# Partial Batch Deletion Recovery Design

## Goal

Make cross-store batch deletion resumable without asking an operator which database to delete next.

## Design

Add a persisted deletion state to the MySQL experiment-run record.  The lifecycle is `active`, `deleting_vectors`, `vectors_deleted_sql_pending`, and `deleted`.  The deletion service updates the state before each irreversible phase.  It deletes vectors first, records `vectors_deleted_sql_pending` after that succeeds, and then deletes the SQL parent row.  A vector deletion error leaves the batch active and prevents SQL deletion.  A SQL error or no-row result after vectors succeed leaves the persisted pending state intact.

When a pending batch is selected, the batch page displays the pending state and offers one confirmed **resume deletion** action.  Resume reads the persisted state and executes only the unfinished SQL-parent deletion; it never invokes the vector store again.  A successful SQL deletion removes the row and its cascaded children.  This makes retries deterministic and avoids duplicate or cross-store ambiguity.

## Testing

Persistence and dashboard tests will cover: state transitions; vector failure blocks SQL; SQL failure persists `vectors_deleted_sql_pending`; resume does not create or call a vector store; and UI success refresh remains gated on a successful SQL deletion.

## Constraints

- No existing batch is deleted during tests.
- No vector reconstruction is attempted.
- A pending state is only written after the corresponding irreversible phase succeeds.
- The existing full-run confirmation remains required for the initial destructive action.
- Do not create a Git commit.
