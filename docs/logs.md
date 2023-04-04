# Cachi2 Logging Standards

## Logging principles

1) Use a Consistent Format: To ensure that logs are easy to read and understand, use a consistent format throughout the system. This format should include the date and time of the log entry, the severity level of the log message, and the message itself.
2) Use Descriptive Severity Levels: Use descriptive severity levels to indicate the importance of a log message. For example, use "INFO" for informational messages, "WARN" for problems that do not interfere with the final result of the request, and "ERROR" for errors that affect the final result of the request.
3) Include Relevant Information: Logs should include relevant information about the action being done.
4) Use Structured Logging: Structured logging is a technique that organizes log messages into a structured format. Structured logging enables users to search, filter, and analyze logs more efficiently.
5) Provide Contextual Information: When possible, provide contextual information that helps users to understand the log message. For example, if the log message indicates that a request has failed, provide additional information about why the request has failed, such as a network error, unsupported dependency, or a malformed input parameter.
6) Use Clear and Concise Language: Use clear and concise language to describe the log messages. Avoid using technical jargon or abbreviations that users may not understand.


## Logging conventions

In our logs, we will use structured log messages, partially formatted in JSON with key-value pairs as described below.

```
TIMESTAMP LOG_LEVEL LOGGER MESSAGE ADDITIONAL_JSON_DATA
```

For example:

```
2023-03-07T11:32:29.948Z WARN pkg_managers.pip No setup.py found in directory /home/fepas/cachi2/workdir/cachito-pip-with-deps, package is likely not pip compatible
2023-03-07T11:32:29.948Z INFO pkg_managers.pip Filling in missing metadata from setup.cfg
2023-03-07T11:32:29.949Z INFO pkg_managers.pip Found metadata {"name": "cachito-pip-with-deps", "version": "1.0.0" }
2023-03-07T11:32:29.949Z INFO pkg_managers.pip Resolved package {"name": "cachito-pip-with-deps", "version": "1.0.0"}
2023-03-07T11:32:29.951Z INFO pkg_managers.pip No hash options used, will not require hashes unless HTTP(S) dependencies are present.
2023-03-07T11:32:29.959Z INFO pkg_managers.pip Dependencies found [{"name": "ruamel-yaml-clib", "version": "0.2.6"}, {"name": "six", "version": "1.16.0"}, {"name": "urllib3", "version": "1.26.7"}, {"name": "cython", "version": "0.29.33"}]
2023-03-07T11:32:29.161Z INFO pkg_managers.pip Downloading dependencies [{"name": "ruamel-yaml-clib", "version": "0.2.6"}, {"name": "six", "version": "1.16.0"}, {"name": "urllib3", "version": "1.26.7"}, {"name": "cython", "version": "0.29.33"}]
2023-03-07T11:32:29.161Z INFO pkg_managers.pip Dependencies downloaded successfully [{"name": "ruamel-yaml-clib", "version": "0.2.6"}, {"name": "six", "version": "1.16.0"}, {"name": "urllib3", "version": "1.26.7"}, {"name": "cython", "version": "0.29.33"}]
2023-03-07T11:32:29.161Z INFO core.general The processing of the packages and dependencies has completed successfully {"output": "deps/pip/"}
```

The meaning of **timestamp** and log level should be self evident. The **logger** name helps understanding which part of Cachi2 is emitting the log. The **message** is a human readable string describing the event being logged. The **json data** contains additional fields useful for searching.

Care should be taken to make sure specific key/value pairs are logged.

### 1. When did it happen?

**Included in:** `TIMESTAMP`

Encode timestamps in UTC/ISO-8601 format at the start of the log line.

### 2. What happened?

**Included in:** `MESSAGE`, `ADDITIONAL_JSON_DATA`

This should appear as a key in the `ADDITIONAL_JSON_DATA` at the end of the log line and can
optionally appear in the human-readable `MESSAGE`.

### 3. Where did it happen?

**Included in:** `LOGGER`

This should indicate which part of Cachi2 is emitting the log.

## Consequences

* By using structured logs that are only partially formatted as JSON, we should strike a balance
  between easy readability and support for centralized queries. It should be easy for a human to
  read Cachi2 logs directly since the first portion of each line contains a human
  readable string early on, while the JSON formatted suffix supports the creation of queries that
  span subsystems in centralized aggregated logs.


Note: This document is based on https://github.com/redhat-appstudio/book/blob/main/ADR/0006-log-conventions.md.
