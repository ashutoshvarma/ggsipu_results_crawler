#!/bin/bash

CLONE_DIR=${CLONE_DIR:=last}
GIT_REPO=${ARCHIVE_GIT_REPO:=GGSIPUResultTracker/ggsipu_results_archive}
GIT_BRANCH=${ARCHIVE_GIT_BRANCH:=dev-local}


# Only use colors if connected to a terminal
if [ -t 1 ]; then
    RED=$(printf '\033[31m')
    GREEN=$(printf '\033[32m')
    YELLOW=$(printf '\033[33m')
    BLUE=$(printf '\033[34m')
    BOLD=$(printf '\033[1m')
    RESET=$(printf '\033[m')
else
    RED=""
    GREEN=""
    YELLOW=""
    BLUE=""
    BOLD=""
    RESET=""
fi


function log_error() { echo "${BOLD}${RED}[ERROR] : ${@}${RESET}"; }
function log_info() { echo "${BOLD}${YELLOW}[INFO] : ${@}${RESET}"; }
function log_success() { echo "${BOLD}${GREEN}[SUCCESS] : ${@}${RESET}"; }

trap "echo '[INFO] Exiting scheduler script.'" EXIT
nargs=$#

function exit_f()
{
    log_info "Script Already Running. Skipping current schedule."
    exit 1
}

function try_lock()
{
    scriptname=$(basename $0)
    pidfile="${scriptname}.lock"

    # lock it
    exec 200>$pidfile
    flock -n 200 || exit_f
    pid=$$
    echo $pid 1>&200  
}

function _git()
{
    git -C ${CLONE_DIR} "$@"
}

function init_git()
{
    # clean $CLONE_DIR from previous instances 
    rm -fr $CLONE_DIR 2>/dev/null

    log_info "Git Clone into ${BLUE}${GIT_BRANCH}${YELLOW} branch of ${GIT_REPO}"
    # use git instead of _git bcuz of -C
    if ! git clone --single-branch --branch ${GIT_BRANCH} --depth=1 https://${GIT_OAUTH_TOKEN}@github.com/${GIT_REPO}.git ${CLONE_DIR}; then
        log_error "Git Clone Failed. Initialisng empty repo with ${BLUE}${GIT_BRANCH}${YELLOW} branch"
        # If ${GIT_BRANCH does not exist}, create empty repo and checkout to ${GIT_BRANCH} so that default master branch is removed
        # https://stackoverflow.com/questions/42871542/how-to-create-a-git-repository-with-the-default-branch-name-other-than-master
        git init ${CLONE_DIR} && _git checkout -b ${GIT_BRANCH}
        _git remote add origin https://${GIT_OAUTH_TOKEN}@github.com/${GIT_REPO}.git
    fi
}


function push_git()
{
    _git add . && _git -c user.name='GGSIPUTracker' -c user.email='ggsipuresulttracker@@gmail.com' commit -m "sync $(date)"
    _git push -u origin ${GIT_BRANCH}
}


function start_script()
{
    log_info "Setting up git environment."
    init_git

    # rm -f inu.py 2>/dev/null

    # log_info "Fetching inu.py from ${BLUE}${FETCH_BRANCH}${YELLOW} branch."
    # wget -q https://raw.githubusercontent.com/ggsipu-usict/ggsipu-notice-tracker/${FETCH_BRANCH}/.py 1>/dev/null
   
    log_info "Starting ${GREEN}grc.py${YELLOW}."
    chmod +x grc.py
    ./grc.py
    log_info "Pushing changes to ${BLUE}${GIT_REPO}${YELLOW}"
    push_git
}


try_lock
start_script