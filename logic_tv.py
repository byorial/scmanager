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
    db_default = {'db_version': '1',}

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
                entity_id = int(req.form['id'])
                ret = LogicTv.create_shortcut(entity_id)
            elif sub == 'remove_shortcut':
                entity_id = int(req.form['id'])
                ret = LogicTv.remove_shortcut(entity_id)
            elif sub == 'metadata_search':
                agent_type = req.form['meta_agent_type']
                title = req.form['meta_search_word']
                ret = ScmUtil.search_metadata(agent_type, title, get_list=True)
            elif sub == 'apply_meta':
                logger.debug(req.form)
                ret = ScmUtil.apply_meta(self.name, req)
            elif sub == 'refresh_info':
                entity_id = int(req.form['id'])
                ret = LogicBase.refresh_info(entity_id)
            elif sub == 'get_children':
                entity_id = int(req.form['id'])
                ret = ScmUtil.get_children(self.name, entity_id)
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
    def create_shortcut(db_id):
        try:
            entity = ModelTvMvItem.get_by_id(db_id)
            shortcut_name = ScmUtil.get_shortcut_name(entity)
            logger.debug('create_shortcut: title(%s), shortcut(%s)', entity.title, shortcut_name)

            # TODO: subfolder rule 적용
            ret  = LibGdrive.create_shortcut(shortcut_name, entity.folder_id, entity.target_folder_id)
            if ret['ret'] != 'success':
                logger.error('failed to create shortcut')
                return { 'ret':'error', 'msg':'생성실패! 로그를 확인해주세요.' }

            shortcut = ret['data']
            # entity update
            entity.shortcut_created = True
            entity.shortcut_folder_id = py_unicode(shortcut['id'])
            entity.gdrive_path = LibGdrive.get_gdrive_full_path(entity.shortcut_folder_id)
            entity.plex_path = ScmUtil.get_plex_path(entity.gdrive_path)
            entity.local_path = ScmUtil.get_local_path(entity.gdrive_path)
            logger.debug('gdpath(%s),plexpath(%s)', entity.gdrive_path, entity.plex_path)
            entity.save()

            rule = ModelRuleItem.get_by_id(entity.rule_id)
            rule.shortcut_count = rule.shortcut_count + 1
            rule.save()

            logger.debug(u'바로가기 생성완료(%s)', entity.shortcut_folder_id)
            ret = { 'ret':'success', 'msg':'바로가기 생성 성공{n}'.format(n=entity.name) }

            if rule.use_plex:
                LogicBase.PlexScannerQueue.put({'id':entity.id, 'agent_type':entity.agent_type, 'action':'ADD', 'now':datetime.now()})
                ret = { 'ret':'success', 'msg':'바로가기 생성 성공{n}, 스캔명령 전송대기'.format(n=entity.name) }
            return ret

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'생성실패! 로그를 확인해주세요.' }


    @staticmethod
    def remove_shortcut(db_id):
        try:
            entity = ModelTvMvItem.get_by_id(db_id)
            logger.debug('remove_shortcut: title(%s), shortcut(%s)', entity.title, os.path.basename(entity.plex_path))
            trash_folder_id = ModelSetting.get('trash_folder_id')

            if ModelSetting.get_bool('use_trash'):
                finfo = LibGdrive.get_file_info(ModelSetting.get('trash_folder_id'))
                if finfo['ret'] != 'success':
                    return { 'ret':'error', 'msg':'삭제실패! 휴지통 폴더ID를 확인해주세요.' }

                ret = LibGdrive.move_file(entity.shortcut_folder_id, entity.target_folder_id, ModelSetting.get('trash_folder_id'))
            else:
                ret = LibGdrive.delete_file(entity.shortcut_folder_id)

            if ret['ret'] != 'success':
                return { 'ret':'error', 'msg':'삭제실패! 로그를 확인해주세요.' }

            entity.shortcut_created = False
            entity.shortcut_folder_id = u''
            entity.save()

            logger.debug(u'바로가기 삭제완료(%s)', entity.shortcut_folder_id)

            rule = ModelRuleItem.get_by_id(entity.rule_id)
            rule.shortcut_count = rule.shortcut_count - 1
            rule.save()
            ret = { 'ret':'success', 'msg':'바로가기 삭제완료{n}'.format(n=entity.title) }

            if rule.use_plex:
                LogicBase.PlexScannerQueue.put({'id':entity.id, 'agent_type':entity.agent_type, 'action':'REMOVE', 'now':datetime.now()})
                ret = { 'ret':'success', 'msg':'바로가기 삭제 성공{n}, 스캔명령 전송대기'.format(n=entity.name) }
            return ret

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'삭제실패! 로그를 확인해주세요.' }

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



    @staticmethod
    def refresh_info(db_id):
        try:
            entity = ModelTvMvItem.get_by_id(db_id)
            info = ScmUtil.info_metadata(entity.agent_type, entity.code, entity.title)
            if info == None:
                logger.debug(u'메타정보 조회실패: %s:%s', rule.agent_type, entity.title)
                return { 'ret':'error', 'msg':'메타정보 조회실패({})'.format(entity.title) }

            entity.code = py_unicode(info['code'])
            entity.status = info['status']
            entity.site = py_unicode(info['site'])
            entity.poster_url = py_unicode(info['poster_url'])
            entity.studio = py_unicode(info['studio'])
            entity.year = py_unicode(info['year'])
            entity.save()
            
            return { 'ret':'success', 'msg':'메타정보 갱신 성공({})'.format(entity.title) }

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'메타정보 갱신 실패! 로그를 확인해주세요.' }

