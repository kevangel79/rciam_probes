#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
import os
import urllib3
import xmltodict
from OpenSSL import crypto
from datetime import datetime
from time import mktime, time, gmtime

from lib.enums import LoggingDefaults, LoggingLevel


def configure_logger(args):
    """
    Get the argument list from command line and configure the logger
    :param args: arguments retrieved from command line
    :type args: dict
    :return: Logger object
    :rtype Logger: Logger object
    """
    # Set the logfile
    if not args.log:
        args.log = LoggingDefaults.LOG_FILE.value
    # Set the log verbosity
    if not args.verbose:
        args.verbose = LoggingLevel.info.value
    else:
        args.verbose = getattr(LoggingLevel, args.verbose).value
    # Create the log file if not present
    if not os.path.exists(args.log):
        open(args.log, 'w').close()

    # Create the Logger
    logger = logging.getLogger(__name__)
    logger.setLevel(args.verbose)

    # Create the Handler for logging data to a file
    logger_handler = logging.FileHandler(args.log)
    logger_handler.setLevel(args.verbose)

    # Create a Formatter for formatting the log messages
    logger_formatter = logging.Formatter(LoggingDefaults.LOG_FORMATTER.value)
    # Add the Formatter to the Handler
    logger_handler.setFormatter(logger_formatter)
    # Add the Handler to the Logger
    logger.addHandler(logger_handler)

    return logger


def get_xml(url):
    """
    Get and parse an xml available through a url
    :param url: URL
    :type url: string

    :return: Data parsed from the xml
    :rtype: dict

    :raises Exception: Exceptions might occurs from the URL format and get request. Or from xml parsing
    """
    http = urllib3.PoolManager()
    response = http.request('GET', url)
    data = xmltodict.parse(response.data)
    return data


def gen_dict_extract(var, key):
    """
    Extract field from nested dictionary with specific key
    :param var: The dictionary to search(haystack)
    :type var: dict

    :param key: The key we are searching(needle)
    :type key: string

    :return: yields a generator object
    :rtype: Iterator[str]
    """
    if isinstance(var, dict):
        for k, v in var.items():
            if key in k:
                yield v
            if isinstance(v, (dict, list)):
                yield from gen_dict_extract(v, key)
    elif isinstance(var, list):
        for d in var:
            yield from gen_dict_extract(d, key)


def fetch_cert_from_type(metadata_dict, cert_type):
    """
    Fetch X509 per type. Supported types [signing, encryption]
    :param metadata_dict: Metadata passed in dictionary format
    :type metadata_dict: dict
    :param cert_type: The type of Certificate i am looking for
    :type cert_type: str

    :return: dictionary of certificates {type<str>: certificate<str>}
    :rtype: dict
    """
    try:
        x509_list_gen = gen_dict_extract(metadata_dict, 'KeyDescriptor')
        x509_list = next(x509_list_gen)
        x509_dict = {}
        # If all is chosen then return a list with all the certificates
        if cert_type == 'all':
            for x509_elem_dict in x509_list:
                mcert_type = ['unknown', x509_elem_dict.get('@use')]['@use' in x509_elem_dict]
                x509_dict[mcert_type] = x509_elem_dict.get('ds:KeyInfo').get('ds:X509Data').get(
                    'ds:X509Certificate')
            return x509_dict
        else:  # If not then return the certificate of the type requested
            for x509_elem_dict in x509_list:
                if x509_elem_dict.get('@use') != cert_type:
                    continue
                x509_dict[x509_elem_dict.get('@use')] = x509_elem_dict.get('ds:KeyInfo').get('ds:X509Data').get(
                    'ds:X509Certificate')
                return x509_dict
                # If no Certificate available raise an exception
        raise Exception("No X509 certificate of type:%s found" % (cert_type))
    except Exception as e:
        # Log the title of the view
        raise Exception(e.args[0]) from e


def evaluate_single_certificate(x509):
    """
    Translate the certificate to its attributes. Calculate the days to expiration
    :param x509: body of x509
    :type x509: string

    :return: Days to Expiration
    :rtype: int

    :return: Certificates Attributes
    :rtype: dict
    """
    try:
        x509_str = "-----BEGIN CERTIFICATE-----\n" + x509 + "\n-----END CERTIFICATE-----\n"
        # Decode the x509 certificate
        x509_obj = crypto.load_certificate(crypto.FILETYPE_PEM, x509_str)
        certData = {
            'Subject': dict(x509_obj.get_subject().get_components()),
            'Issuer': dict(x509_obj.get_issuer().get_components()),
            'serialNumber': x509_obj.get_serial_number(),
            'version': x509_obj.get_version(),
            'not Before': datetime.strptime(x509_obj.get_notBefore().decode(), '%Y%m%d%H%M%SZ'),
            'not After': datetime.strptime(x509_obj.get_notAfter().decode(), '%Y%m%d%H%M%SZ'),
        }
        certData['Subject'] = {y.decode(): certData['Subject'].get(y).decode() for y in certData['Subject'].keys()}
        certData['Issuer'] = {y.decode(): certData['Issuer'].get(y).decode() for y in certData['Issuer'].keys()}

    except Exception as e:
        # Throw the exception back to the main thread to catch
        raise Exception from e

    cert_expire = certData['not After']
    now = datetime.fromtimestamp(mktime(gmtime(time())))
    expiration_days = (cert_expire - now).days

    return expiration_days, certData
