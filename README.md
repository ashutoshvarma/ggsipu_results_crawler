# **grc.py** - _the uncompromising results crawler_
> Inspired from the [ggsipu-notice-tracker](https://github.com/ggsipu-usict/ggsipu-notice-tracker)

_grc_ aim is to automate the extraction and archiving of data from ggsipu results pdfs.

## How it Works ?
It scrap and process the _new_ results pdf from results website (`RESULTS_URL`) and save 
the last processed pdf (`LAST_JSON`) for future reference.

For pdf processing, [ggsipu_result](https://github.com/ashutoshvarma/ggsipu_result) module is used
and extracted data is passed to specialized classes inherited from `BaseDump` class which uploads/archive
the data respectively.

Currently we have only Firebase Realtime Database (for json data) and Firebase CloudStorage (for student's images)
as Dumps.

## Requirements
Need Python >= 3.8

To install requirements:
```
pip -r requirements.txt
```

## How to Use ?
There are two ways to use _grc_:
- Local - `python grc.py`
- In Server/CI - `bash start.sh`

### Local - `python grc.py`
Since grc.py uses Firebase as backend you need to define two environment for authentication:
- `FIREBASE_CONFIG` - For Firebase options, must have `databaseURL` and `storageBucket` set in it. Read More [here](https://firebase.google.com/docs/admin/setup#initialize-without-parameters).
- `GOOGLE_APPLICATION_CREDENTIALS` - For authenticate with Google Cloud. Read More [here](https://cloud.google.com/docs/authentication/production#providing_credentials_to_your_application)

### CI/Server/Container - `bash start.sh`
`start.sh` is a wrapper script for grc.py to run it in a isolated environment
where file system may be temporary (ephemeral filesystem) like Heroku, CI Servers, Containers.

This loads last pdf info from [git repo](https://github.com/GGSIPUResultTracker/ggsipu_results_archive) and start the grc.py and upload the last pdf details to git repo.

Same as running grc.py, it requires firebase and github authentication details using environment variables:-
- `GCLOUD_KEY` - Contents of Google Cloud Auth Key file (`GOOGLE_APPLICATION_CREDENTIALS`).
- `ARCHIVE_GIT_REPO` - Github repo to save last pdf details in, example `ashutoshvarma/results_archive`
- `ARCHIVE_GIT_BRANCH` - Git branch for `ARCHIVE_GIT_REPO`
- `GIT_OAUTH_TOKEN` - Github Auth Key with push rights to `ARCHIVE_GIT_REPO`
- `FIREBASE_CONFIG`

## Extra Configuration
See 'GLOBAL OPTIONs' in grc.py



