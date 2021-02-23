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
from framework import db, scheduler, path_data, socketio, SystemModelSetting, app, celery, py_unicode
from framework.util import Util
from framework.common.util import headers, get_json_with_auth_session
from framework.common.plugin import LogicModuleBase, default_route_socketio
from tool_expand import ToolExpandFileProcess

# 패키지
from lib_gdrive import LibGdrive
from .logic_base import LogicBase
from .models import ModelRuleItem, ModelAvItem
from .utils import ScmUtil

from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

#from lib_metadata.server_util import MetadataServerUtil
#########################################################

class LogicAv(LogicModuleBase):
    def __init__(self, P):
        super(LogicAv, self).__init__(P, 'itemlist')
        self.name = 'av'

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        if sub == 'itemlist':
            arg['categories'] = ','.join(ScmUtil.get_rule_names(self.name))
            arg['agent_types'] = ','.join(ScmUtil.get_agent_types(self.name))
        return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)


    def process_ajax(self, sub, req):
        try:
            logger.debug('AV-AJAX: sub(%s)', sub)
            logger.debug(req.form)
            if sub == 'web_list':
                ret = ModelAvItem.web_list(req)
            elif sub == 'create_shortcut':
                db_id = int(req.form['id'])
                LogicBase.ShortcutJobQueue.put({'id':db_id, 'module_name':self.name})
                ret = { 'ret':'success', 'msg':'바로가기 생성 요청 완료' }
            elif sub == 'remove_shortcut':
                db_id = int(req.form['id'])
                LogicBase.RemoveJobQueue.put({'id':db_id, 'module_name':self.name, 'target':'shortcut'})
                ret = { 'ret':'success', 'msg':'바로가기 삭제 요청 완료' }
            elif sub == 'metadata_search':
                agent_type = req.form['meta_agent_type']
                title = req.form['meta_search_word']
                ret = ScmUtil.search_metadata(agent_type, title, get_list=True)
            elif sub == 'apply_meta':
                ret = ScmUtil.apply_meta(self.name, req)
            elif sub == 'refresh_info':
                ret = ScmUtil.refresh_info(self.name, req)
            elif sub == 'get_children':
                db_id = int(req.form['id'])
                ret = ScmUtil.get_children(self.name, db_id)
            elif sub == 'change_excluded':
                db_id = int(req.form['id'])
                action = req.form['action']
                ret = ScmUtil.change_excluded(self.name, db_id, action)
            return jsonify(ret)

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})

    @staticmethod
    def get_av_rule_names():
        from .logic_gdrive import ModelRuleItem
        try:
            rule_entities = ModelRuleItem.get_all_av_entities()
            rule_names = list(set([x.name for x in rule_entities]))
            return rule_names
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_av_agent_types():
        from .logic_gdrive import ModelRuleItem
        try:
            rule_entities = ModelRuleItem.get_all_av_entities()
            agent_types = list(set([x.agent_type for x in rule_entities]))
            return agent_types
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

