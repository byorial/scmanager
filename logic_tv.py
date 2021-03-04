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

class LogicTv(LogicModuleBase):
    def __init__(self, P):
        super(LogicTv, self).__init__(P, 'itemlist')
        self.name = 'tv'

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        P.logger.debug('sub:%s', sub)
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
                ret = ModelTvMvItem.web_list(self.name, req)
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
            elif sub == 'remove_item':
                db_id = int(req.form['id'])
                entity = ModelTvMvItem.get_by_id(db_id)
                entity.delete(entity.id)
                ret = { 'ret':'success', 'msg':'아이템 항목 삭제  완료' }
            elif sub == 'get_children':
                db_id = int(req.form['id'])
                ret = ScmUtil.get_children(self.name, db_id)
            elif sub == 'change_excluded':
                db_id = int(req.form['id'])
                action = req.form['action']
                ret = ScmUtil.change_excluded(self.name, db_id, action)
            elif sub == 'msg_request':
                msg = req.form['msg']
                ret = ScmUtil.send_message('tv', msg)
            return jsonify(ret)

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})

    def scheduler_function(self):
        logger.debug('tv scheduler function!!!!!!!!!!!!!!')
        LogicTv.task()

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
    def task():
        try:
            logger.debug('[tv_schedule] start tv scheduler')
            service = None
            service = LibGdrive.sa_authorize(ModelSetting.get('gdrive_auth_path'), return_service=True)
            if service == None:
                data = {'type':'warning', 'msg':u'서비스계정 인증에 실패하여 스케쥴러를 실행할 수 없습니다.'}
                socketio.emit("notify", data, namespace='/framework', broadcate=True)
                logger.error('[tv_schdule]: failed to authorize sa accounts(%s)', ModelSetting.get('gdrive_auth_path'))

            entities = ModelTvMvItem.get_onair_entities_with_shortcut()
            count = len(entities)
            logger.debug('[tv_schedule] target onair item: %d', count)

            for entity in entities:
                children = LibGdrive.get_children(entity.folder_id, time_after=entity.updated_time, service=service)
                if children == None:
                    logger.error('failed to get children files: skip!')
                    continue

                logger.debug(u'[tv_schedule] title:{}, 에피소드 추가 내역: {}'.format(entity.title, u'없음' if len(children) == 0 else '{} 건'.format(len(children))))
                if len(children) > 0:
                    logger.debug('[tv_schedule] new episode found, send_scan(%s)', entity.title)
                    fpath = os.path.join(entity.plex_path, children[0]['name'])
                    LogicBase.PlexScannerQueue.put({'id':entity.id, 'agent_type':entity.agent_type, 'path':fpath, 'action':'REFRESH', 'now':datetime.now()})

            logger.debug('[tv_schedule] end tv scheduler')

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
