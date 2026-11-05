# ADR 0006: Pseudonymise, and keep only what the indicators need

Status: Accepted

## Context
The registry sends a name, a national identifier and an opaque person id. The indicators need to know whether the same
person appears twice, roughly how old they are, which team they belong to and whether they have a chronic condition. They
do not need to know who the person is. A copy of the analytic database that leaks should not be joinable back to the
registry.

## Decision
1. **The name is not stored**, and the national identifier is only *checked* (its two check digits) and then dropped. A
   record whose identifier fails the check is counted as rejected and never stored.
2. **The person is stored as a keyed pseudonym**: HMAC-SHA256 of the registry person id, truncated to 130 bits, tagged with
   the id of the key (`pk1.…`). Without the key the pseudonym cannot be joined back; with a *plain* hash of a small space
   it could be reversed by trying every value, which is why it is keyed.
3. **The birth date is reduced to its month** (the first day of it). Age in months is all the indicators use.
4. **The registry's own record id is not stored anywhere**, not even as the synchronisation position (ADR 0003 keeps only a
   time). An earlier version kept the last id as a cursor; it was removed.
5. **The key is required in production**: the configuration refuses to start with the demonstration key or one shorter
   than 32 characters.
6. **The claim is verified, not just stated.** `find_values` walks every text-like column of every table for a list of
   values; the lab runs it for the names, identifiers and ids of 40 people and shows that it finds none. A scan that looks
   at nothing proves nothing, so it reports how many columns it examined, and a test plants a value to show the scan can
   see it.
7. **Errors keep no row data.** A failed run records the *kind* of failure (and a database error is reduced to its code),
   because an error message from the database can quote the row that failed.

## Rejected alternatives
- **A plain hash.** Reversible by enumeration for identifiers with a small space.
- **Encrypt, keep the key beside the data.** The goal is that the analytic layer *cannot* be joined back; encryption makes
  it possible for whoever holds the key to read it. The pseudonym is one way.
- **Store the identifier and restrict access.** One mistaken query or backup defeats it.
- **Keep the full birth date.** The indicators work on months.
- **Mask on the way out.** A column that holds the value is a column that leaks.

## Consequences
- (+) A leaked copy of the analytic layer says who is in which team with which condition, but not who they are.
- (+) The property is a test, not a sentence in a document.
- (−) **There is no re-keying tool.** The tag makes a rotation possible (rows made with the old key can be found), but the
  job itself is not part of this repository.
- (−) Without the registry, nothing can answer "who is this pseudonym?" That is intended.
- (−) The registry's person id is hashed as the registry writes it. If the registry re-issues ids, the same person becomes
  two pseudonyms; there is no record linkage between people (listed in the README).
