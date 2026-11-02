# accurev2git
This script was developed from the work found in 
[accurev-to-git](https://github.com/fuzzmz/accurev-to-git) as a working script
for converting accurev history to git. The process employed is very simple and
will only convert a single stream (no sub-streams). 

> [!IMPORTANT]
> **This process _only_ converts the specified stream.** A trade-off of this
> approach is that the resulting git repository will represent authorship
> information based on the user that promoted each transaction into the
> specified AccuRev stream. This is not a perfect representation of the actual
> authorship history of the stream. This is typically the case when converting a
> release or "master" stream (the most likely use-case for this script). In such
> situations, it is common that the promotor of the transaction is bundling the
> work of more than one user into a single release. In the resulting git
> repository, that user will git the "credit/blame" for all the bundled changes
> in the transaction.

## Conversion Algorithm
The conversion process is somewhat brute force. After pulling the transaction
history from the stream, each transaction is processed by populating over the 
current contents of the git folder's contents (`accurev pop` with the `-O` 
flag). `git add -A` is run, followed by a `git commit`. If there are no file 
changes for a transaction, no commit is performed.

## Notes
> [!WARNING]
> `accurev2git` might have serious bugs. Use at your own risk and check its
> work. I do not plan to maintain it indefinitely. If you have an improvement,
> feel free to let me know or just fork it!

* Due to the need to full populate the entire stream for each transaction, this
  can take a very long time, depending on the size of the stream contents, the
  number of transactions to process and external factors such as network speed,
  disk IO, etc.
* `accurev2git` is capable of resuming from a prior run cleanly. To interrupt a 
  run, press `CTRL-C`. To resume, simply run with the same arguments and 
  `accurev2git` will pick up where it left off based on the git commit history.

## Requirements
The following tools are required for running the script:
* AccuRev CLI
* Git
* Python (the script has no non-standard dependencies)

## Usage
Before running, customize config.py with mapping information. Without the 
`AUTHOR_MAP` configuration, default mapping will be performed, but this is rarely
going to give the results you want. When running the utility, the transaction
history will be compared to `AUTHOR_MAP` and any missing AccuRev user mappings
will be listed prior to beginning the conversion.
```
migrate.py [-h] [--since SINCE] [-u ACCUREV_USER] [-p ACCUREV_PASS] accurevBranch repoLocation

positional arguments:
  accurevBranch         Name of the AccuRev stream/branch to migrate
  repoLocation          Target folder for the Git repository

options:
  -h, --help            Show this help message and exit
  --since SINCE         Only migrate transactions >= this date (Format: YYYY-MM-DD)
  -u, --user ACCUREV_USER
                        AccuRev username for automatic login. 
                        If not provided, interactive login is supported.
  -p, --password ACCUREV_PASS
                        AccuRev password for automatic login.
                        If not provided, interactive login is supported.
```
