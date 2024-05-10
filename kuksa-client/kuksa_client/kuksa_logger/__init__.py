# /********************************************************************************
# * Copyright (c) 2024 Contributors to the Eclipse Foundation
# *
# * See the NOTICE file(s) distributed with this work for additional
# * information regarding copyright ownership.
# *
# * This program and the accompanying materials are made available under the
# * terms of the Apache License 2.0 which is available at
# * http://www.apache.org/licenses/LICENSE-2.0
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

# This file contains a logger that could be useful for clients using kuksa-python-sdk

import logging
import sys
import os


class KuksaLogger:
    def init_logging(self):
        # Example
        #
        # Set log level to debug
        #   LOG_LEVEL=debug kuksa-client
        #
        # Set log level to INFO, but for dbcfeederlib.databrokerclientwrapper set it to DEBUG
        #   LOG_LEVEL=info,dbcfeederlib.databrokerclientwrapper=debug kuksa-client
        #
        #

        loglevels = self.parse_env_log(os.environ.get("LOG_LEVEL"))

        # set root loglevel etc
        self.init_root_logging(loglevels["root"])

        # set loglevels for other loggers
        for logger, level in loglevels.items():
            if logger != "root":
                logging.getLogger(logger).setLevel(level)

    def init_root_logging(self, loglevel):
        """Set up console logger"""
        # create console handler and set level to debug. This just means that it can show DEBUG messages.
        # What actually is shown is controlled by logging configuration
        console_logger = logging.StreamHandler()
        console_logger.setLevel(logging.DEBUG)

        # create formatter
        if sys.stdout.isatty():
            formatter = ColorFormatter()
        else:
            formatter = logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s: %(message)s"
            )

        # add formatter to console_logger
        console_logger.setFormatter(formatter)

        # add console_logger as a global handler
        root_logger = logging.getLogger()
        root_logger.setLevel(loglevel)
        root_logger.addHandler(console_logger)

    def parse_env_log(self, env_log, default=logging.INFO):
        def parse_level(specified_level, default=default):
            if isinstance(specified_level, str):
                if specified_level.lower() in [
                    "debug",
                    "info",
                    "warn",
                    "warning",
                    "error",
                    "critical",
                                               ]:
                    return specified_level.upper()
                raise ValueError(f"could not parse '{specified_level}' as a log level")
            return default

        parsed_loglevels = {}

        if env_log is not None:
            log_specs = env_log.split(",")
            for log_spec in log_specs:
                spec_parts = log_spec.split("=")
                if len(spec_parts) == 1:
                    # This is a root level spec
                    if "root" in parsed_loglevels:
                        raise ValueError("multiple root loglevels specified")
                    parsed_loglevels["root"] = parse_level(spec_parts[0])
                if len(spec_parts) == 2:
                    logger_name = spec_parts[0]
                    logger_level = spec_parts[1]
                    parsed_loglevels[logger_name] = parse_level(logger_level)

        if "root" not in parsed_loglevels:
            parsed_loglevels["root"] = default

        return parsed_loglevels


class ColorFormatter(logging.Formatter):
    """Color formatter that can be used for terminals"""
    FORMAT = "{time} {{loglevel}} {logger} {msg}".format(
        time="\x1b[2m%(asctime)s\x1b[0m",  # grey
        logger="\x1b[2m%(name)s:\x1b[0m",  # grey
        msg="%(message)s",
    )
    FORMATS = {
        logging.DEBUG: FORMAT.format(loglevel="\x1b[34mDEBUG\x1b[0m"),  # blue
        logging.INFO: FORMAT.format(loglevel="\x1b[32mINFO\x1b[0m"),  # green
        logging.WARNING: FORMAT.format(loglevel="\x1b[33mWARNING\x1b[0m"),  # yellow
        logging.ERROR: FORMAT.format(loglevel="\x1b[31mERROR\x1b[0m"),  # red
        logging.CRITICAL: FORMAT.format(loglevel="\x1b[31mCRITICAL\x1b[0m"),  # red
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)
