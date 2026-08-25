# logalizer

Export Kibana logs as CSV from the command line — via the Kibana 7.17
Reporting API. No third-party dependencies (pure Python stdlib).

`logalizer` authenticates to Kibana with basic auth, submits a CSV reporting
job, polls until it completes, and writes the result to stdout or a file. It is
built for both humans and scripts: clean exit codes and a strict stdout/stderr
separation so `logalizer ... > out.csv` always yields only CSV on stdout.

## Install

    pip install logalizer

Requires Python 3.10+.

## Configure

    logalizer --init

Interactive wizard that validates your credentials and lets you pick a space and
index pattern from live lists. Or set environment variables:

    export KIBANA_URL=https://...
    export KIBANA_USERNAME=...
    export KIBANA_PASSWORD=...

## Usage

    # test connectivity and configuration
    logalizer --ping

    # discover what's available
    logalizer --list-spaces
    logalizer --list-indices --space <space>
    logalizer --list-fields --index '<pattern>'

    # export logs as CSV
    logalizer -i '<index-pattern>' --query 'level:error' --last 24h \
        --fields '@timestamp,level,msg' -o errors.csv

Run `logalizer --help` for the full reference and `logalizer --help-json` for a
machine-readable flag schema.

## Release

Publishing is automated via GitHub Actions Trusted Publishing.

One-time setup on PyPI: project settings → Publishing → add a "pending
publisher" with owner `isdmx`, repository `logalizer`, workflow `publish.yml`,
environment `pypi`.

After that, cut a release with:

    git tag v0.1.0
    git push --tags

CI builds the sdist + wheel and uploads them to PyPI automatically.

## License

MIT
