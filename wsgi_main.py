#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
# wsgi_main.py
#
# Copyright (C) 2014 Kano Computing Ltd.
# License: http://www.gnu.org/licenses/gpl-2.0.txt GNU General Public License v2
#
# wsgi_main.py - Provide an entry to Feedback reports via a WSGI interface.
# This allows for serving reports behind Gunicorn, uWSGI or equivalent.
#
# If using gunicorn, you can test it like this:
#
# $ gunicorn -b 127.0.0.1:9000 wsgi_main
#

import os
import drfeedback
import tempfile
import cgi
import shutil
import stat
from urlparse import urljoin

# The filesystem directory where all HTML reports are stored
# And the URL to this directory exposed via the web server
reports_directory = '/var/local/feedback-reports'
reports_url = 'http://dev.kano.me/feedback-reports'


def _save_report_(report_id, html_data, tarfile_name, directory=reports_directory):
    # Saves the HTML report file on the local filesystem
    filename = '%s.html' % report_id
    output_tarfile = '%s.tgz' % report_id

    try:
        assert (os.path.exists(directory))
        abs_filename = os.path.join(directory, filename)
        htmlfile = open(abs_filename, 'w')
        htmlfile.write(html_data)
        htmlfile.close()

        abs_output_tarfile = os.path.join(directory, output_tarfile)
        shutil.copy(tarfile_name,  abs_output_tarfile)
        os.chmod(abs_output_tarfile,
                 stat.S_IRUSR |
                 stat.S_IWUSR |
                 stat.S_IRGRP |
                 stat.S_IROTH)
        return filename
    except:
        raise


def _dump_environment_(environment):
    # Just for debugging purposes
    for key in environment:
        print '%s=%s' % (key, environment[key])


def _get_hosturl_(environment):
    # Construct and return the full URL that reaches the feedback html files
    hosturl = urljoin('%s://%s' % (environment['wsgi.url_scheme'],
                                   environment['HTTP_HOST']), environment['PATH_INFO'])
    return hosturl


def application(environ, start_response):

    full_dump = True
    debug = False

    # dump the environment to follow possible problems
    # any exceptions raised in this code will be returned as reason 500 to the client
    if debug:
        _dump_environment_(environ)
        print 'Full host URL:', _get_hosturl_(environ)

    # the environment variable CONTENT_LENGTH may be empty or missing
    try:
        request_body_size = int(environ.get('CONTENT_LENGTH', 0))
    except (ValueError):
        raise

    # Fetch the post data into a CGI FieldStorage object
    # And do some minimal fields validation
    fs = cgi.FieldStorage(fp=environ['wsgi.input'], environ=environ)

    verb = fs.getfirst('verb')
    assert(verb == 'report')

    report_id = fs.getfirst('report_id')
    assert(len(report_id) > 0)

    targz = fs.getfirst('tarfiles')
    assert(len(targz) > 0)

    print 'Received request with verb: %s, report_id: %s, data (tar.gz): %d bytes.' % \
          (verb, report_id, len(targz))

    # Save the targz data in a temporary file
    html_tmpfile = tempfile.NamedTemporaryFile(mode='w+b')
    html_tmpfile.write(targz)
    html_tmpfile.flush()

    # Send the tar.gz file for analysis
    report_html = drfeedback.analyze(html_tmpfile.name, idname=report_id,
                                     full_dump=full_dump)

    # Save the report in the local filesystem to be served via nginx
    report_file = _save_report_(report_id, report_html, html_tmpfile.name)
    assert (report_file)

    # closing the tempfile to efectively remove it
    html_tmpfile.close()


    # Send the results to the client
    start_response('200 OK', [('Content-Type', 'text/html')])
    ok_message = 'Feedback request processed successfully: id=%s url=%s' % \
        (report_id, '%s/%s' % (reports_url, report_file))

    print ok_message
    return [ok_message]
