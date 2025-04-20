#!python3
#
# Copyright (c) 2025 Lukasbel
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
# 
# vss2git.py - Convert SourceSafe project to Git
#


import sys
import argparse
import shutil
import os
import stat
import subprocess
from pathlib import Path
import re
import datetime
from filecmp import dircmp

VERSION = '2025-03-24'

DEFAULT_SSEXE = r'c:\Program Files (x86)\Microsoft Visual SourceSafe\ss.exe'
DEFAULT_GITEXE = r'c:\Program Files\Git\bin\git.exe'
DEFAULT_PROJECT_BASE = '$'
DEFAULT_NUM_LABELS = 10
DEFAULT_EXCLUDED = ['vssver2.scc','mssccprj.scc']
DEFAULT_BRANCH = 'master'
DEFAULT_USER = ''
DEFAULT_PASSWORD = ''
GIT = 'git'
VSS = 'vss'


class SSRunner:
    def __init__(self, ss, repoBase, user, passwd, projBase):
        self.ss = ss
        self.repoBase = repoBase
        self.user = user
        self.passwd = passwd
        self.projBase = projBase
    
    def GetHistory(self, project):
        env = os.environ
        env['SSDIR'] = self.repoBase
        env['SSUSER'] = self.user
        env['SSPWD'] = self.passwd
        cmd = [self.ss, 'history', f'{self.projBase}/{project}']
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, errors='replace')
        if res.returncode:
            raise FileNotFoundError(res.stderr)
        return res.stdout

    def GetAtLabel(self, project, label, outPath):
        env = os.environ
        env['SSDIR'] = self.repoBase
        env['SSUSER'] = self.user
        env['SSPWD'] = self.passwd
        cmd = [self.ss, 'get', f'{self.projBase}/{project}', '-I-N', '-r', '-gf', '-gl.']
        if label:
            cmd.append(f'-vl{label}')
        res = subprocess.run(cmd, env=env, cwd=outPath, capture_output=True, text=True, errors='replace')
        # Set all files r/w
        for dirpath, dirnames, filenames in os.walk(outPath):
            os.chmod(dirpath, stat.S_IWRITE)
            for filename in filenames:
                os.chmod(os.path.join(dirpath, filename), stat.S_IWRITE)
        return res.returncode


class GITRunner:
    def __init__(self, git, repoDir):
        self.git = git
        self.repoDir = repoDir
    
    def Init(self):
        return self.gitExec('init')

    def Add(self, fileList):
        return self.gitExec(['add', '--'] + fileList)

    def AddAll(self):
        return self.gitExec(['add', '-A'])

    def Remove(self, path, recursive=False):
        cmd = ['rm']
        if recursive:
            cmd.append('-r')
        cmd.append('-f')
        cmd.append('--')
        cmd.append(path)
        return self.gitExec(cmd)

    def Commit(self, user, comment, timestamp):
        env = os.environ
        env['GIT_AUTHOR_NAME'] = user
        env['GIT_AUTHOR_EMAIL'] = ''
        env['GIT_AUTHOR_DATE'] = timestamp.isoformat(' ')
        env['GIT_COMMITTER_NAME'] = user
        env['GIT_COMMITTER_EMAIL'] = ''
        env['GIT_COMMITTER_DATE'] = timestamp.isoformat(' ')
        cmd = ['commit']
        if not comment:
            cmd.append('--allow-empty-message')
            cmd.append('--no-edit')
        cmd.append('-m')
        cmd.append(comment)
        return self.gitExec(cmd, env)

    def Tag(self, label):
        return self.gitExec(['tag','--',label])

    def Set(self, args):
        return self.gitExec(args)

    def Push(self, branch):
        # First push the repo
        cmd = ['push', '-u', 'origin', f'HEAD:{branch}']
        retCmd = self.gitExec(cmd)
        if retCmd == 0:
            # Push the tags
            retCmd = self.gitExec(['push', 'origin', '--tags'])
        return retCmd

    def gitExec(self, args, env=os.environ):
        cmd = [Path(self.git).resolve()]
        if type(args) is list:
            cmd += args
        else:
            cmd += args.split(' ')
        res = subprocess.run(cmd, env=env, cwd=self.repoDir, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            print(f'git command failed: {res.stderr}')
        return res.returncode

class HistoryParser:
    tsRE = re.compile(r'^User:\s(.+)\s+Date:\s+(.+?)\s+Time:\s+([0-9:]+)$')
    verRE = re.compile(r'(\d+)[._](\d+)[._](\d+)[._](\d+)')
    cmtRE = re.compile(r'^Label comment.+?(JIRA)[\s_-]*(\d+)(.*)', re.I)

    def __init__(self, component):
        self.component = component
        self.lblRE = re.compile(r'^Label:\s+"?(.*' + component + r'.+?)"?$', re.I)

    def ParseLabels(self, history):
        mode = 0
        label = ""
        lastLabel = ""
        tsDate = ""
        tsTime = ""
        user = ""
        comment = ""

        releases = []

        try:
            for line in history.splitlines():
                line.strip()
                if line.startswith('*****'):
                    if label and tsDate and tsTime:
                        d = datetime.datetime.strptime(tsDate + ' ' + tsTime, '%d/%m/%y %H:%M')
                        if lastLabel != label:
                            releases.append([label, d, comment, user])
                            lastLabel = label
                    mode = 0
                    label = ""
                    tsDate = ""
                    tsTime = ""
                    user = ""
                    comment = ""
                m = self.lblRE.match(line)
                if m:
                    mode = 1
                    label = m.group(1)
                    continue
                if mode == 1:
                    m = self.tsRE.match(line)
                    if m:
                        user, tsDate, tsTime = m.group(1).strip(), m.group(2), m.group(3)
                    m = self.cmtRE.search(line)
                    if m:
                        comment = m.group(1) + '-' + m.group(2) + ' ' + m.group(3)
                        comment = comment.replace('"','').replace("'", '').replace('\\', '/')
                        mode = 2
                elif mode == 2:
                    comment += '\r\n' + line.replace('"','').replace("'", '').replace('\\', '/')


        except Exception as e:
            print(f"Failed to parse history. Releases might not be complete: {e}")
        return releases

def remove_readonly(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)

def ignore_files(path, names):
    global args
    return args.excluded

def ProcessDiff(diffs, relPath):
    # diff_files contains changed files
    for fn in diffs.diff_files:
        print(f'  *{relPath / fn}')
        git.Add([relPath / fn])
    # left_only contains removed files
    for fn in diffs.left_only:
        print(f'  -{ relPath / fn}')
        rmFile = Path(diffs.left) / fn
        if rmFile.is_dir():
            git.Remove(relPath / fn, True)
        else:
            rmFile.unlink(missing_ok=True)
            git.Remove(relPath / fn)
    # right_only contains new files
    for fn in diffs.right_only:
        print(f'  +{relPath / fn}')
        git.Add([relPath / fn])
    ## Recurse directories
    for cd in diffs.common_dirs:
        ProcessDiff(diffs.subdirs[cd], relPath / cd)

# Command line arguments
parser = argparse.ArgumentParser(description=f'vss2git - Convert Visual SourceSafe project to Git ({VERSION})')
parser.add_argument('ssdir', type=str, help='SourceSafe repository folder containing srcsafe.ini')
parser.add_argument('project', type=str, help='SourceSafe project')
group = parser.add_mutually_exclusive_group()
group.add_argument('-n', dest='numLabels', type=int, default=DEFAULT_NUM_LABELS, help=f'Number of labels to convert. Default: {DEFAULT_NUM_LABELS}')
group.add_argument('-d', dest='fromDate', type=str, help='Start date of labels to convert. Format: YYYY-MM-DD')
parser.add_argument('-e', dest='excluded', nargs='*', default=DEFAULT_EXCLUDED, action='append', help=f'File patterns to exclude. Default: {" ".join(DEFAULT_EXCLUDED)}')
parser.add_argument('-l', dest='label', type=str, default=None, help='Name used in label if different from project name')
parser.add_argument('-L', dest='list', action='store_true', help='List releases')
parser.add_argument('-u', dest='user', default=DEFAULT_USER, type=str, help='SourceSafe login user name')
parser.add_argument('-p', dest='passwd', default=DEFAULT_PASSWORD, type=str, help='SourceSafe login password')
parser.add_argument('-B', dest='branch', default=DEFAULT_BRANCH, type=str, help='Head branch to initial push. Default: master')
parser.add_argument('-s', dest='step', action='store_true', help='Step through each conversion of a release')
parser.add_argument('-R', dest='remote', default=None, type=str, help='Git repository URL to set as remote. Default: not set')
parser.add_argument('-P', dest='push', action='store_true', help='Push the repository to the remote server')
parser.add_argument('--attr-file', dest='attrFile', default=None, type=str, help='File to copy in repository as .gitattributes')
parser.add_argument('--ss-exe', dest='ss', type=str, default=DEFAULT_SSEXE, help='Full path to SourceSafe command line executable SS.EXE')
parser.add_argument('--project-base', dest='projectBase', type=str, default=DEFAULT_PROJECT_BASE, help=f'The project base folder within SourceSafe (Default: {DEFAULT_PROJECT_BASE})')
parser.add_argument('--git-exe', dest='git', type=str, default=DEFAULT_GITEXE, help='Full path to Git command line executable git.exe')
args = parser.parse_args()

if args.label is None:
    # Label pattern is same as project name
    args.label = args.project

# Get full history of project in SourceSafe
ss = SSRunner(args.ss, args.ssdir, args.user, args.passwd, args.projectBase)
try:
    print(f'Retrieving history for {args.project}')
    hist = ss.GetHistory(args.project)
except Exception as e:
    print(f'Failed to obtain history for {args.project}: {e}')
    sys.exit(2)

# Parse the labels from history and extract version, Jira, user and date/time
print('Parsing history')
hp = HistoryParser(args.label)
releases = hp.ParseLabels(hist)
print(f'Found {len(releases)} release labels')

if args.list:
    for rel in releases:
        print(f'{rel[0]}\t{rel[1]}\t{rel[2]}')
    sys.exit(0)

if args.numLabels > len(releases):
    args.numLabels = len(releases)
    print(f'Adjusted number of labels to process to {args.numLabels}')

# Prepare working folders
workdir = Path.cwd()

# Delete previous work folders
vssPath = workdir / VSS / args.project
gitPath = workdir / GIT / args.project
try:
    if vssPath.exists():
        print(f'Removing vss work folder: {vssPath}')
        shutil.rmtree(vssPath, onerror=remove_readonly)
    if gitPath.exists():
        print(f'Removing git repo: {gitPath}')
        shutil.rmtree(gitPath, onerror=remove_readonly)
except Exception as e:
    print(f'Failed to delete work folders for {args.project}: {e}')
    sys.exit(2)

# Create work folders
try:
    vssPath.mkdir(parents=True, exist_ok=True)
    gitPath.mkdir(parents=True, exist_ok=True)
except Exception as e:
    print(f'Failed to create work folders for {args.project}: {e}')

# Dump full history
try:
    histFile = workdir / VSS / f'{args.project}_history.txt'
    with histFile.open('wt', errors='ignore') as f:
        f.write(hist)
    print(f'History written to {histFile}')
except Exception as e:
    print(f'Failed to write history to {histFile}: {e}')

# Initialise the git repo
git = GITRunner(args.git, gitPath)

print(f'Running: git init in {gitPath}')
if git.Init() != 0:
    print('git init failed')
    sys.exit(3)

# Is a remote repository URL given
if args.remote:
    print(f'Setting remote repository URL to {args.remote}')
    git.Set(['remote', 'add', 'origin', args.remote])

# If start date specified, calculate the number of entries that are more recent
if args.fromDate:
    try:
        startDate = datetime.datetime.fromisoformat(args.fromDate)
        relCount = 0
        for rel in releases:
            if startDate >= rel[1]:
                break
            relCount += 1
        if relCount > 0:
            args.numLabels = relCount
            print(f'Start date {args.fromDate} contains {relCount} releases')
        else:
            print(f'No releases found that are newer than {args.fromDate}')
            sys.exit(1)
    except Exception as e:
        print(f'Failed to process start date: {args.fromDate}')

# Process the releases in reverse order (oldest to latest)
first = True
label = None
for relIdx in range(args.numLabels, 0, -1):
    prevLabel = label
    vssLabel, timestamp, desc, user = releases[relIdx-1]
    print('-' * 80)
    print(f'Processing label {vssLabel}')
    # Remove invalid chars from label so it can be used as a tag and folder name
    label = re.sub(r'[^\w\d.-]', '_', vssLabel)
    if label != vssLabel:
        print(f'Label adjusted to {label}')
    # Get label from SourceSafe
    vssLblPath = vssPath / label
    vssLblPath.mkdir()
    print(f'Get {vssLabel} to folder {vssLblPath}')
    getRes = ss.GetAtLabel(args.project, vssLabel, vssLblPath)
    print(f'Result of SS Get {getRes}')
    if getRes == 0:
        if args.step:
            input('Press ENTER to continue (CTRL-C to abort): ')
        if first: # First get: add all files to git
            first = False
            shutil.copytree(vssLblPath, gitPath, ignore=ignore_files, dirs_exist_ok=True)
            print(f'First source set. Add all files to git')
            if args.attrFile:
                gitAttrFile = gitPath / '.gitattributes'
                print(f'Copy {args.attrFile} to {gitAttrFile}')
                shutil.copyfile(args.attrFile, gitAttrFile)
            gitRes = git.AddAll()
            if gitRes == 0:
                print('Doing git commit')
                gitRes = git.Commit(user, desc, timestamp)
                print(f'Result of Commit {gitRes}')
                git.Tag(label)
        else: # 2nd and next label
            vssPrevLblPath = vssPath / prevLabel
            diffs = dircmp(vssPrevLblPath, vssLblPath, ignore=args.excluded)
            shutil.copytree(vssLblPath, gitPath, ignore=ignore_files, dirs_exist_ok=True)
            ProcessDiff(diffs, Path(''))
            print('Doing git commit')
            gitRes = git.Commit(user, desc, timestamp)
            print(f'Result of Commit {gitRes}')
            git.Tag(label)
    else:
        print(f'Failed to get SS label {vssLabel}')

# Should we push
if args.push:
    print(f'Pushing repository to {args.branch} branch')
    git.Push(args.branch)
