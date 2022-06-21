# -*- coding: utf-8 -*-
#########################################################
# python
import os, sys, traceback, re, json, threading, time, shutil
from datetime import datetime, timedelta
# third-party
import requests
# third-party
from flask import request, render_template, jsonify, redirect
from sqlalchemy import or_, and_, func, not_, desc
import random

# sjva 공용
from framework import db, scheduler, path_data, socketio, SystemModelSetting, app, celery, py_unicode, py_urllib, py_queue
from framework.util import Util
from framework.common.util import headers, get_json_with_auth_session
from framework.common.plugin import LogicModuleBase, default_route_socketio
from tool_expand import ToolExpandFileProcess
from tool_base import ToolUtil

# GDrive Lib
from lib_gdrive import LibGdrive
from .logic_base import LogicBase
from .models import ModelRuleItem, ModelTvMvItem
from .utils import ScmUtil

# 패키지
from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

#########################################################

class LogicMv(LogicModuleBase):
    def __init__(self, P):
        super(LogicMv, self).__init__(P, 'itemlist')
        self.name = 'mv'

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        P.logger.debug('sub:%s', sub)
        arg['proxy_url'] = ToolUtil.make_apikey_url(f'/{package_name}/api/proxy')
        if sub == 'null': sub = 'itemlist'
        if sub == 'itemlist':
            arg['categories'] = ','.join(ScmUtil.get_rule_names(self.name))
            arg['agent_types'] = ','.join(ScmUtil.get_agent_types(self.name))
            arg['genres'] = ','.join(ScmUtil.get_all_genres(self.name))
        return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)

    def process_ajax(self, sub, req):
        try:
            ret = {'ret':'success', 'list':[]}
            logger.debug('TVMV-AJAX %s', sub)
            logger.debug(req.form)

            if sub == 'web_list':
                ret = ModelTvMvItem.web_list('movie', req)
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
                ret = LogicBase.refresh_info(self.name, req)
            elif sub == 'get_children':
                db_id = int(req.form['id'])
                ret = ScmUtil.get_children(self.name, db_id)
            elif sub == 'remove_item':
                db_id = int(req.form['id'])
                entity = ModelTvMvItem.get_by_id(db_id)
                entity.delete(entity.id)
                ret = { 'ret':'success', 'msg':'아이템 항목 삭제  완료' }
            elif sub == 'change_excluded':
                db_id = int(req.form['id'])
                action = req.form['action']
                ret = ScmUtil.change_excluded(self.name, db_id, action)
            elif sub == 'msg_request':
                msg = req.form['msg']
                ret = ScmUtil.send_message('movie', msg)
            elif sub == 'get_genres':
                rule_name = req.form['rulename']
                ret = ScmUtil.get_all_genres_by_rule_name(rule_name)
            return jsonify(ret)

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})

    def scheduler_function(self):
        logger.debug('scheduler function!!!!!!!!!!!!!!')
        if app.config['config']['use_celery']:
            result = LogicBase.task.apply_async()
            result.get()
        else:
            LogicBase.task()

    #########################################################
    @staticmethod
    def create_gd_entity(info):
        try:
            entity = ModelTvMvItem(info['name'], info['folder_id'], info['rule_name'], info['rule_id'])
            if entity == None: return None
            entity.rule_name = py_unicode(info['rule_name'])
            entity.agent_type = py_unicode(info['agent_type'])
            entity.root_folder_id = py_unicode(info['root_folder_id'])
            entity.target_folder_id = py_unicode(info['target_folder_id'])
            entity.mime_type = py_unicode(info['mime_type'])
            entity.parent_folder_id = py_unicode(info['parent_folder_id'])
            entity.code = py_unicode(info['code'])
            entity.status = info['status']
            entity.title = py_unicode(info['title'])
            entity.site = py_unicode(info['site'])
            entity.studio = py_unicode(info['studio'])
            entity.poster_url = py_unicode(info['poster_url'])
            entity.year = info['year']
            entity.genre = info['genre']
            entity.country = py_unicode(info['country'])
            entity.save()
            return entity
        
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def apply_meta(req):
        try:
            db_id = int(req.form['id'])
            entity = ModelTvMvItem.get_by_id(db_id)

            code = req.form['code']
            title = req.form['title']
            site = req.form['site']

            info = ScmUtil.info_metadata(entity.agent_type, code, title)
            if info == None:
                logger.error(u'메타정보 조회실패: %s:%s', rule.agent_type, title)
                return { 'ret':'error', 'msg':'"{}"의 메타정보 조회실패.'.format(title) }

            entity.code = py_unicode(info['code'])
            entity.status = info['status']
            entity.site = py_unicode(info['site'])
            entity.poster_url = py_unicode(info['poster_url'])
            entity.studio = py_unicode(info['studio'])
            entity.year = py_unicode(info['year'])
            entity.genre = py_unicode(info['genre'])
            entity.title = py_unicode(title)
            entity.save()
            
            return { 'ret':'success', 'msg':'"{}"의 메타정보 적용완료.'.format(entity.title) }

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'에러발생! 로그를 확인해주세요.' }

