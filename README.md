# accurev2git
This script was developed from the work found in 
[accurev-to-git](https://github.com/fuzzmz/accurev-to-git) as a working script
for converting accurev history to git. The process employed is very simple and
will only convert a single stream (no sub-streams). 

## Notes
The conversion process is somewhat brute force. After pulling the transaction
history from the stream, each transaction is processed by populating over the 
current contents of the git folder's contents (`accurev pop` with the `-O` 
flag). `git add -A` is run, followed by a `git commit`. This seems to be the
only way to correctly get all changes. If there are no file changes for a
transaction, no commit is perfomed.

This can take a very long time, depending on the size of the stream contents and
external factors (network speed, disk IO, etc.).

`accurev2git` is capable of resuming from a prior run cleanly. To interrupt a 
run, press `CTRL-C`. To resume, simply run with the same arguments and 
`accurev2git` will pick up where it left off based on the git commit history.

> [!WARNING]
> `accurev2git` might have serious bugs. Use at your own risk and check its
> work. I do not plan to maintain it indefinitely. If you have an improvement,
> feel free to let me know or just fork it!

## Requirements
The following tools are required for running the script:
* AccuRev CLI
* Git
* Python (the script has no non-standard dependencies)

## Usage
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