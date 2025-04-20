# vss2git
Quick and dirty Python script to convert a SourceSafe project to a Git repository.
Initially created to convert our projects in VSS to BitBucket, using the Jira issue integration.

The script makes use the the console SourceSafe client **SS.exe** . It does not parse the VSS files itself.

Use `-h` to get help.

```
usage: vss2git.py [-h] [-n NUMLABELS | -d FROMDATE] [-e [EXCLUDED ...]] [-l LABEL] [-L] [-u USER]
                  [-p PASSWD] [-B BRANCH] [-R REMOTE] [-P] [--attr-file ATTRFILE] [--ss-exe SS]
                  [--project-base PROJECTBASE] [--git-exe GIT]
                  ssdir project

vss2git - Convert Visual SourceSafe project to Git (2025-03-17)

positional arguments:
  ssdir                 SourceSafe repository folder containing srcsafe.ini
  project               SourceSafe project

options:
  -h, --help            show this help message and exit
  -n NUMLABELS          Number of labels to convert. Default: 10
  -d FROMDATE           Start date of labels to convert. Format: YYYY-MM-DD
  -e [EXCLUDED ...]     File patterns to exclude. Default: vssver2.scc mssccprj.scc
  -l LABEL              Name used in label if different from project name
  -L                    List releases
  -u USER               SourceSafe login user name
  -p PASSWD             SourceSafe login password
  -B BRANCH             Head branch to initial push. Default: master
  -R REMOTE             Git repository URL to set as remote. Default: not set
  -P                    Push the repository to the remote server
  --attr-file ATTRFILE  File to copy in repository as .gitattributes
  --ss-exe SS           Full path to SourceSafe command line executable SS.EXE
  --project-base PROJECTBASE
                        The project base folder within SourceSafe (Default: $)
  --git-exe GIT         Full path to Git command line executable git.exe
```

The script works at project level, set the project base to the level above the project to convert.
E.g. if project is at `$/Example/Projects/Project1`, then set `--project-base $/Example/Projects`.

Conversion is done based on __releases__ that are labelled with some release marker and version.
By default, labels named **Project_1_2_3_4** or **Project_1.2.3.4** are detected as a released version. if the label is different from the project name, use `-l` to set the base for the label release detection.
Comments to use on git commit are extracted from a Jira issue reference in the label comment.

Anyway, adjust the regex statements in the `HistoryParser` class to your needs.

If need to convert many projects, set the `DEFAULT_...` constants at the top the script accordingly.

The overall processing of the script is as follows:

1. Get the history of the project and extract `releases`.
2. Decide how many releases to convert.
3. From the oldest release up to the latest:
   - Get sources with the VSS label
   - Diff the folder with the previous release (initially add all files to the empty git repo)
   - The diff is rudimentary in that it detects only new or deleted files, but not renamed files. These are treated as removed and added under their new name.
   - Add the changed files to git
   - Commit
   - Tag using the label. Note that the label might be corrected to be a valid git tag name.
4. If remote URL set, optionally push the repo to the remote server.
