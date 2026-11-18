# A vs B disagreements

A = proposed by an LLM; B = second model (Gemini), labelled blind. **final** is the gold label (rows left blank are excluded from scoring and counted). Uncited sentences are `unsupported` by rule (reason `rule: uncited`); rows below the disagreements were adjudicated although A and B agreed.

| row | tag | sentence or question | A | B | reason | final |
|---|---|---|---|---|---|---|
| `a01.0` | real | In WAL mode the database file and the ‑wal file are used together: (refs none) | supported | skip | rule: uncited | unsupported |
| `a01.1` | real | Readers continue to read the original database pages. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a01.10` | real | — writers append, readers run concurrently, checkpoint interaction, single writer limitation. (refs none) | supported | skip | rule: uncited | unsupported |
| `a01.2` | real | They never need to wait for a writer because the writer never overwrites those pages. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a01.3` | real | Writers only append new changes to the end of the ‑wal file. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a01.4` | real | Since they are only adding data, they do not interfere with the pages that readers are using, so readers and the single active writer can run at the same time. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a01.5` | real | Only one writer may be active at any moment because all writes go to the same WAL file. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a01.6` | real | A checkpoint copies pages from the WAL back into the main file, but it must stop if a reader is still using a WAL page, so a long‑running read can temporarily block the checkpoint. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a01.7` | real | When no readers are using the WAL, the writer can rewind the WAL to keep its size bounded. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a01.8` | real | These behaviors are described in the SQLite documentation and notes on WAL mode. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a02.0` | real | A WAL checkpoint copies the pages that have been recorded in the write‑ahead log back into the main database file, and (when no other connections are using the WAL) resets the ‑wal file so it can be reused. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a02.1` | real | This transfers the pending changes from the WAL to the database and clears the log for future writes. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a03.0` | real | No. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a06.0` | real | Feed the starter twice a day (e.g., 50 g flour + 50 g water each time) when it’s kept at room temperature. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a16.0` | real | The sources give conflicting information: (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a16.2` | real | Another note says the stand‑up has been cancelled permanently. (refs [2]) | unsupported | supported | adjudicated | unsupported |
| `a16.3` | real | Because the sources disagree, both statements are reported. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a16.5` | subtle | The standup is at 10:30 every weekday in the Lighthouse room. (refs [1]) | unsupported | partial | adjudicated | unsupported |
| `a18.1` | real | No other provided source mentions retrospectives, so this is the only available information. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c02.0` | real | Yes. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c02.1` | real | When you are doing a large bulk‑import you can increase the automatic‑checkpoint threshold so that SQLite does not start checkpointing in the middle of the import and slow it down. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c02.3` | real | The official SQLite documentation says the default automatic checkpoint runs when the WAL reaches roughly 1000 pages (≈ 4 MiB) and that you can change this behavior (e.g., raise the limit or disable automatic checkpointing) if the frequent checkpoints are undesirable for large write transactions. (refs [2, 4]) | partial | supported | adjudicated | partial |
| `c02.4` | real | The two sources differ on the exact default size (500 pages vs. 1000 pages), but both agree that increasing the limit (or disabling automatic checkpointing and running manual checkpoints later) is a valid way to improve bulk‑import performance. (refs none) | partial | unsupported | rule: uncited | unsupported |
| `c03.0` | real | The recommended replacement stretch varies: (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c03.3` | real | So the suggested threshold is either 0.5 % or 0.75 % stretch, depending on which recommendation you follow. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c04.0` | real | The recommended pressure for 25 mm road tyres varies in the sources: (refs none) | supported | skip | rule: uncited | unsupported |
| `c04.3` | real | So, the general guideline is 80‑90 psi, but if you’re riding on rough surfaces a lower pressure around 70 psi may be preferred. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c05.2` | real | Because the official docs are authoritative, the correct answer is that `asyncio.Queue` is not thread‑safe, and the note contradicts the documented behavior. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c06.0` | real | Yes. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c07.0` | real | Yes. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c07.1` | real | SQLite runs an automatic checkpoint whenever the WAL file grows past its size limit, so a prolonged burst of writes that quickly fills the WAL will cause many checkpoints to be issued. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c07.4` | real | Thus, while the exact default page count differs (500 vs. 1000 pages), both sources agree that long write bursts can cause frequent automatic WAL checkpoints. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c08.0` | real | The sources give conflicting advice: (refs none) | supported | skip | rule: uncited | unsupported |
| `c08.3` | real | So, according to the available information, some experts consider 0.5 % stretch overly cautious, while others consider it the proper replacement point. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `c08.4` | real | The answer depends on which recommendation you follow. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `i03.0` | real | The sources give conflicting information: (refs none) | supported | unsupported | rule: uncited | unsupported |
| `i03.1` | real | Source 1 says the daily stand‑up is still scheduled on Tuesdays at 10:30 starting next week, held in the Lighthouse room. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `i03.3` | real | Because the two notes disagree and neither is clearly more authoritative, both statements are reported. (refs none) | skip | unsupported | rule: uncited | unsupported |
| `i06.0` | real | The roastery delivers the beans on Wednesdays. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `m02.1` | real | The scheduled time for the daily stand‑up on Tuesdays is 10:30, but a facilities notice states that the stand‑up has been cancelled permanently. (refs [2, 3]) | partial | supported | adjudicated | partial |
| `m02.2` | real | The sources conflict on this point. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `m03.2` | real | > The sources disagree on the thread‑safety of `asyncio.Queue`. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `m03.3` | real | The authoritative Python docs (source 2) say it is not thread‑safe, so you should treat it as such unless you have additional evidence that the implementation has changed. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `m03.5` | real | By default, `sqlite3.connect(..., check_same_thread=True)` raises a `ProgrammingError` if the connection is used from a different thread. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `m03.7` | real | > Therefore, a SQLite connection is not thread‑safe by default; it can be shared across threads only with `check_same_thread=False` and proper user‑level synchronization. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `m04.0` | real | PEP 8 line length: The style guide limits code lines to 79 characters (with docstrings/comments limited to 72). (refs none) | supported | unsupported | rule: uncited | unsupported |
| `m05.1` | real | When you open a connection with `sqlite3.connect()`, the `timeout` argument controls how long SQLite will wait for a locked table before raising an `OperationalError`. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `m07.1` | real | Closing a connection with `autocommit=False` – When `autocommit` is `False` (PEP 249‑compliant mode), SQLite keeps a transaction open. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `n13.0` | real | `asyncio.PriorityQueue` retrieves items in priority order, with the lowest priority value first. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u02.0` | real | Readers must examine the WAL file to locate any pages that have been appended there. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u02.1` | real | As the WAL grows, the amount of data each reader has to scan increases, so the time spent checking the WAL rises proportionally to its size. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u04.0` | real | Yes – a WAL database can still be used when shared‑memory support is missing, provided the connection is put into `EXCLUSIVE` locking mode before the first WAL access. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u05.0` | real | No. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u05.1` | real | In normal operation a checkpoint does not truncate the WAL file; it simply copies the pages back to the database and then overwrites the WAL from the beginning. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u05.2` | real | Only when the `journal_size_limit` pragma is set (or when using the special `SQLITE_CHECKPOINT_TRUNCATE` option) will a checkpoint actually truncate the file. (refs [1, 2]) | partial | supported | adjudicated | partial |
| `u06.0` | real | The WAL file can grow without bound when SQLite is prevented from checkpointing it or when a single transaction writes a lot of data: (refs none) | supported | skip | rule: uncited | unsupported |
| `u06.2` | real | Checkpoint starvation – A checkpoint can only finish when no other connections have a read transaction open. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u06.6` | real | These conditions allow the WAL file to expand indefinitely. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u07.0` | real | When an `asyncio.Queue` has reached its `maxsize`, calling `await queue.put(item)` does not raise an error; instead the coroutine waits (blocks) until a slot becomes free—i.e., until another task removes an item with `get()`—and then the item is inserted. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u08.0` | real | Use `asyncio.wait_for()` to wrap the queue coroutine you want to limit. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u10.0` | real | `asyncio.Queue.shutdown(immediate=True)` puts the queue into an immediate shutdown mode. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u10.1` | real | The queue is drained completely, its count of unfinished tasks is reduced by the number of tasks that were removed, and: (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u10.2` | real | If the unfinished‑tasks count reaches zero, any coroutines waiting on `join()` are unblocked. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u10.3` | real | Callers that are blocked on `get()` are unblocked and will raise `QueueShutDown` because the queue is now empty. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u13.0` | real | PEP 8 recommends grouping imports in three sections, separated by a blank line: (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u13.1` | real | Standard library imports (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u13.2` | real | Related third‑party imports (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u16.0` | real | PEP 8 does not prescribe a preference for single‑quoted versus double‑quoted strings. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u18.0` | real | By default the `sqlite3` module sets `check_same_thread=True`. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u19.0` | real | Placeholders keep the query text separate from the data you supply, so the SQLite driver can bind the values safely. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u19.2` | real | Using `?` (qmark) or named placeholders lets `cursor.execute()` handle the quoting and escaping for you, eliminating that risk. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u20.0` | real | No. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u20.1` | real | A `sqlite3.Connection` used as a context manager only commits or rolls back transactions; it does not close the connection. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `u22.0` | real | When `autocommit` is set to False, closing the connection automatically rolls back any transaction that has uncommitted changes. (refs none) | supported | unsupported | rule: uncited | unsupported |
| `a16` | question | behaviour | wrong | correct | adjudicated | wrong |
| `c05` | question | behaviour | flags_conflict | picks_right | adjudicated | picks_right |
| `m02` | question | behaviour | wrong | correct | adjudicated | wrong |
| `m06` | question | behaviour | incomplete | correct | adjudicated | correct |
| `m08` | question | behaviour | incomplete | correct | adjudicated | incomplete |
| `n08` | question | behaviour | partly_answered | answered | adjudicated | answered |
| `m08.1` | real | PEP 8 recommends that exception class names end with the suffix “Error” when the exception represents an error. (refs [2]) — A and B agreed | supported | supported | wrong citation | unsupported |
