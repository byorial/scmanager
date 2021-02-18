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
from .models import ModelRuleItem, ModelAvItem
from .utils import ScmUtil

from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

#from lib_metadata.server_util import MetadataServerUtil
#########################################################

class LogicAv(LogicModuleBase):
    db_default = {'db_version': '1',}

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
                entity_id = int(req.form['id'])
                ret = LogicAv.create_shortcut(entity_id)
            elif sub == 'create_shortcut':
                entity_id = int(req.form['id'])
                ret = LogicAv.create_shortcut(entity_id)
            elif sub == 'metadata_search':
                agent_type = req.form['meta_agent_type']
                title = req.form['meta_search_word']
                ret = ScmUtil.search_metadata(agent_type, title, get_list=True)
            elif sub == 'apply_meta':
                ret = ScmUtil.apply_meta(self.name, req)
            elif sub == 'get_children':
                entity_id = int(req.form['id'])
                ret = ScmUtil.get_children(self.name, entity_id)

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

    @staticmethod
    def create_shortcut(db_id):
        try:
            entity = ModelAvItem.get_by_id(db_id)
            rule = ModelRuleItem.get_by_id(entity.rule_id)

            shortcut_name = ScmUtil.get_shortcut_name(entity)
            logger.debug('create_shortcut: title(%s), shortcut(%s)', entity.title, shortcut_name)

            # 하위폴더 생성
            if rule.use_subfolder:
                new_parent_id = ScmUtil.create_subfolder(rule.subfolder_rule, entity)
                if new_parent_id != None:
                    ret = LibGdrive.create_shortcut(shortcut_name, entity.folder_id, new_parent_id)
            else:
                ret = LibGdrive.create_shortcut(shortcut_name, entity.folder_id, entity.target_folder_id)
            # TODO: 에러처리

            # entity update
            entity.shortcut_created = True
            entity.shortcut_folder_id = py_unicode(shortcut['id'])
            entity.gdrive_path = LibGdrive.get_gdrive_full_path(entity.shortcut_folder_id)
            entity.plex_path = LogicBase.get_plex_path(entity.gdrive_path)
            entity.local_path = ScmUtil.get_local_path(entity.gdrive_path)
            logger.debug('gdpath(%s),plexpath(%s)', entity.gdrive_path, entity.plex_path)
            entity.save()

            rule = ModelRuleItem.get_by_id(entity.rule_id)
            rule.shortcut_count = rule.shortcut_count + 1
            rule.save()

            logger.debug(u'바로가기 생성완료(%s)', entity.shortcut_folder_id)
            ret = { 'ret':'success', 'msg':'바로가기 생성 성공{n}'.format(n=entity.name) }

            if rule.use_plex:
                LogicBase.PlexScannerQueue.put({'id':entity.id, 'now':datetime.now()})
                ret = { 'ret':'success', 'msg':'바로가기 생성 성공{n}, 스캔명령 전송대기'.format(n=entity.name) }
            return ret

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'생성실패! 로그를 확인해주세요.' }

    @staticmethod
    def remove_shortcut(db_id):
        try:
            entity = ModelAvItem.get_by_id(db_id)
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


    #########################################################

