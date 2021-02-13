# -*- coding: utf-8 -*-
#########################################################
# python
import os, sys, traceback, re, json, threading, time, shutil
from datetime import datetime
# third-party
import requests
# third-party
from flask import request, render_template, jsonify, redirect
from sqlalchemy import or_, and_, func, not_, desc

# sjva 공용
from framework import db, scheduler, path_data, socketio, SystemModelSetting, app, celery
from framework.util import Util
from framework.common.util import headers, get_json_with_auth_session
from framework.common.plugin import LogicModuleBase, default_route_socketio
from tool_expand import ToolExpandFileProcess

# 패키지
from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

from .logic_gdrive import LogicGdrive, ModelRuleItem, ModelGdriveItem

#from lib_metadata.server_util import MetadataServerUtil
#########################################################

class LogicPlex(LogicModuleBase):
    db_default = {
        'plex_scan_delay' : '30',
        'plex_scan_min_limit' : '10',
        'plex_meta_update_interval' : '10',
    }

    def __init__(self, P):
        super(LogicPlex, self).__init__(P, 'setting')
        self.name = 'plex'

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        if sub == 'setting':
            job_id = '%s_%s' % (self.P.package_name, self.name)
            arg['scheduler'] = str(scheduler.is_include(job_id))
            arg['is_running'] = str(scheduler.is_running(job_id))
        return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)


    def process_ajax(self, sub, req):
        try:
            return jsonify({'ret':'success', 'data':newfilename})

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})

    def scheduler_function(self):
        if app.config['config']['use_celery']:
            result = LogicPlex.task.apply_async()
            result.get()
        else:
            LogicPlex.task()

    #########################################################

    @staticmethod
    @celery.task
    def task():
        while True:
            try:
                logger.debug('main routine')
                time.sleep(60)

            except Exception as e:
                logger.debug('Exception:%s', e)
                logger.debug(traceback.format_exc())
