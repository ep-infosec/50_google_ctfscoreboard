# Copyright 2016 Google LLC. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import flask
from flask import logging as flask_logging
import logging
import os
from werkzeug import exceptions
from werkzeug import utils as werkzeug_utils
import flask_scss

from scoreboard import logger

# Singleton app instance
_app_singleton = None


def on_appengine():
    """Returns true if we're running on AppEngine."""
    runtime = os.environ.get('SERVER_SOFTWARE', '')
    gae_env = os.environ.get('GAE_ENV', '')
    return ((gae_env != '') or
            runtime.startswith('Development/') or
            runtime.startswith('Google App Engine/'))


def create_app(config=None):
    app = flask.Flask(
            'scoreboard',
            static_folder='../static',
            template_folder='../templates',
            )
    app.config.from_object('scoreboard.config_defaults.Defaults')
    if config is not None:
        app.config.update(**config)

    if not on_appengine():
        # Configure Scss to watch the files
        scss_compiler = flask_scss.Scss(
                app, static_dir='static/css', asset_dir='static/scss')
        scss_compiler.update_scss()

    for c in exceptions.default_exceptions.keys():
        app.register_error_handler(c, api_error_handler)

    setup_logging(app)
    return app


def load_config_file(app=None):
    app = app or get_app()
    try:
        app.config.from_object('config')
    except werkzeug_utils.ImportStringError:
        pass
    app.config.from_envvar('SCOREBOARD_CONFIG', silent=True)
    setup_logging(app)  # reset logs


def setup_logging(app):
    log_formatter = logger.Formatter(
            '%(asctime)s %(levelname)8s [%(filename)s:%(lineno)d] '
            '%(client)s %(message)s')
    # log to files unless on AppEngine
    if not on_appengine():
        # Main logger
        if not (app.debug or app.config.get('TESTING')):
            handler = logging.FileHandler(
                app.config.get('LOGFILE', '/tmp/scoreboard.wsgi.log'))
            handler.setLevel(logging.INFO)
            handler.setFormatter(log_formatter)
            app.logger.addHandler(handler)
        else:
            app.logger.handlers[0].setFormatter(log_formatter)

        # Challenge logger
        handler = logging.FileHandler(
            app.config.get('CHALLENGELOG', '/tmp/scoreboard.challenge.log'))
        handler.setLevel(logging.INFO)
        handler.setFormatter(logger.Formatter(
            '%(asctime)s %(client)s %(message)s'))
        local_logger = logging.getLogger('scoreboard')
        local_logger.addHandler(handler)
        app.challenge_log = local_logger
    else:
        app.challenge_log = app.logger
        try:
            import google.cloud.logging
            from google.cloud.logging import handlers
            client = google.cloud.logging.Client()
            client.setup_logging()
            handler = handlers.CloudLoggingHandler(client)
            app.logger.addHandler(handler)
            handler.setLevel(logging.INFO)
            return app
        except ImportError as ex:
            logging.error('Failed setting up logging: %s', ex)
        if not app.logger.handlers:
            app.logger.addHandler(flask_logging.default_handler)
            app.logger.handlers[0].setFormatter(log_formatter)
            logging.getLogger().handlers[0].setFormatter(log_formatter)

    return app


def api_error_handler(ex):
    """Handle errors as appropriate depending on path."""
    error_titles = {
        401: 'Unauthorized',
        403: 'Forbidden',
        500: 'Internal Error',
    }
    try:
        status_code = ex.code
    except AttributeError:
        status_code = 500
    if flask.request.path.startswith('/api/'):
        app = get_app()
        app.logger.error(str(ex))
        if app.config.get('DEBUG', False):
            resp = flask.jsonify(message=str(ex))
        else:
            resp = flask.jsonify(message='Internal Server Error')
        resp.status_code = status_code
        return resp
    return flask.make_response(
        flask.render_template(
            'error.html', exc=ex,
            title=error_titles.get(status_code, 'Error')),
        status_code)


def get_app():
    global _app_singleton
    if _app_singleton is None:
        _app_singleton = create_app()
    return _app_singleton
