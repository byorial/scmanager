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
import guessit

# sjva 공용
from framework import db, scheduler, path_data, socketio, SystemModelSetting, app, celery, py_unicode, py_urllib, py_queue
from framework.util import Util
from framework.common.util import headers, get_json_with_auth_session
from framework.common.plugin import LogicModuleBase, default_route_socketio
from framework.job import Job
from tool_expand import ToolExpandFileProcess

# GDrive Lib
from lib_gdrive import LibGdrive
from .models import ModelRuleItem, ModelTvMvItem, ModelAvItem
from .utils import ScmUtil

# 패키지
from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

#########################################################

class LogicBase(LogicModuleBase):
    db_default = {
        'db_version' : '1',
        # 숨김 메뉴
        'use_av'     : 'True',
        'use_setting': 'True',

        # API
        'gdrive_token_path' : os.path.join(path_data, package_name, 'token.pickle'),
        'gdrive_creds_path' : os.path.join(path_data, package_name, 'credentials.json'),
        'gdrive_sa_auth'    : u'False',
        'gdrive_user_auth'  : u'False',
        'gdrive_auth_code'  : u'',
        'gdrive_auth_path'  : os.path.join(path_data, 'rclone_expand', 'accounts'),

        # 일반
        'scmbase_auto_start' : u'False',
        'scmbase_interval'   : u'30',
        'gdrive_thread_num' : u'5',
        'gdrive_local_path_rule': u'/Video/plex|/mnt/plex',
        'avlist_show_poster': u'True',
        'use_trash': u'False',
        'trash_folder_id': u'',

        # plex
        'plex_remove_library': u'True',
        'gdrive_plex_path_rule' : u'/Video/plex|/mnt/plex',
        #'plex_scan_delay': u'30',
        #'plex_scan_min_limit': u'10',

        # for ktv
        'tv_auto_start': u'False',
        'tv_scheduler': u'False',
        'tv_interval': u'30',
        'ktv_meta_result_limit_per_site': u'3',
        #'ktv_use_season_folder': u'True',
        'ktv_shortcut_name_rule': '{title} ({year})',

        # for ftv
        'ftv_meta_result_limit_per_site': u'3',
        #'ftv_use_season_folder': u'True',
        'ftv_shortcut_name_rule': u'{title} ({year})',

        # for movie
        'movie_shortcut_name_rule': u'{title} ({year})',

        # for avdvd
        'avdvd_shortcut_name_rule': u'{ui_code}',

        # for avama
        'avama_shortcut_name_rule': u'{ui_code}',
    }

    RuleHandlerThread = None
    RuleJobQueue = None
    Services = None

    PlexScannerThread = None
    PlexScannerQueue = None

    ShortcutCreateThread = None
    ShortcutJobQueue = None

    RemoveHandlerThread = None
    RemoveJobQueue = None


    def __init__(self, P):
        super(LogicBase, self).__init__(P, 'rulelist')
        self.name = 'scmbase'

    def plugin_load(self):
        self.initialize()

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        P.logger.debug('sub:%s', sub)
        if sub == 'setting':
            job_id = '%s_%s' % (self.P.package_name, self.name)
            job_id2 = '%s_%s' % (self.P.package_name, 'tv')
            arg['scheduler'] = str(scheduler.is_include(job_id))
            arg['is_running'] = str(scheduler.is_running(job_id))
            arg['is_include_tv'] = str(scheduler.is_include(job_id2))
            arg['is_running_tv'] = str(scheduler.is_running(job_id2))
            arg['use_av'] = ModelSetting.get_bool('use_av')
            arg['use_setting'] = ModelSetting.get_bool('use_setting')
        elif sub == 'rulelist':
            arg['categories'] = ','.join(ScmUtil.get_rule_names(self.name))
            arg['agent_types'] = ','.join(ScmUtil.get_all_agent_types())
            arg['use_av'] = ModelSetting.get_bool('use_av')
            arg['use_setting'] = ModelSetting.get_bool('use_setting')
        return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)

    def process_ajax(self, sub, req):
        try:
            ret = {'ret':'success', 'list':[]}
            logger.debug('BASE-AJAX %s', sub)
            logger.debug(req.form)

            if sub == 'rule_list':
                ret = ModelRuleItem.web_list(req)
            elif sub == 'tv_scheduler':
                if req.form['scheduler'] == 'true':
                    LogicBase.scheduler_start()
                else:
                    LogicBase.scheduler_stop()
            elif sub == 'get_gdrive_path':
                folder_id = req.form['folder_id']
                gdrive_path = LibGdrive.get_gdrive_full_path(folder_id)
                logger.debug('gdrive_path: %s', gdrive_path)
                return jsonify({'ret':'success', 'data':gdrive_path})
            elif sub == 'register_rule':
                logger.debug(req.form)
                ret = ScmUtil.register_rule(req)
            elif sub == 'execute_rule':
                rule_id = int(req.form['id'])
                req = {'rule_id': rule_id}
                LogicBase.RuleJobQueue.put(req)
                return jsonify({'ret':'success', 'msg':'실행요청 완료'})
            elif sub == 'modify_rule':
                ret = ScmUtil.modify_rule(req)
            elif sub == 'update_rule_count':
                ret = ScmUtil.update_rule_count(req)
            elif sub == 'remove_rule':
                ret = LogicBase.remove_handler(req)
            elif sub == 'web_list':
                ret = ModelTvMvItem.web_list(req)
            elif sub == 'metadata_search':
                agent_type = req.form['meta_agent_type']
                title = req.form['meta_search_word']
                ret = ScmUtil.search_metadata(agent_type, title, get_list=True)
            elif sub == 'auth_step1':
                url, _ = LibGdrive.auth_step1(credentials=ModelSetting.get('gdrive_creds_path'), 
                        token=ModelSetting.get('gdrive_token_path'))
                return jsonify(url)
            elif sub == 'auth_step2':
                code = req.form['code']
                LibGdrive.auth_step2(code, token=ModelSetting.get('gdrive_token_path'))
                return jsonify(os.path.exists(ModelSetting.get('gdrive_token_path')))
            elif sub == 'auth_by_token':
                ret = LibGdrive.user_authorize(token=ModelSetting.get('gdrive_token_path'))
                if ret:
                    logger.debug('gdrive user auth succeed')
                    ret = {'ret':'success', 'msg':u'구글드라이브 API인증 완료'}
                else:
                    logger.error('gdrive user auth failed')
                    ret = {'ret':'success', 'msg':u'구글드라이브 API인증 실패'}
            elif sub == 'sa_auth':
                json_path = req.form['path']
                LogicBase.Services = LibGdrive.sa_authorize_for_multiple_connection(ModelSetting.get('gdrive_auth_path'), ModelSetting.get_int('gdrive_thread_num'))
                ret = LibGdrive.sa_authorize(json_path)
                if ret == True: ModelSetting.set('gdrive_auth_path', json_path)
            return jsonify(ret)

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'msg':str(e)})


    def scheduler_function(self):
        logger.debug('scheduler function!!!!!!!!!!!!!!')
        LogicBase.task()
        """
        if app.config['config']['use_celery']:
            result = LogicBase.task.apply_async()
            result.get()
        else:
            LogicBase.task()
        """

    #########################################################
    @staticmethod
    def initialize():
        try:
            json_path = ModelSetting.get('gdrive_auth_path')
            if not os.path.exists(json_path):
                logger.error('can not recognize gdrive_auth_path(%s)', json_path)
                data = {'type':'warning', 'msg':'인증파일(.json) 경로를 확인해주세요.'}
                socketio.emit('notify', data, namespace='/framework', broadcast=True)
                return

            creds_dir = os.path.dirname(ModelSetting.get('gdrive_creds_path'))
            if not os.path.isdir(creds_dir): os.mkdirs(creds_dir)

            ret = LibGdrive.sa_authorize(json_path)
            if ret == True: ModelSetting.set('gdrive_sa_auth', 'True')
            else: ModelSetting.set('gdrive_sa_auth', 'False')
            if ret == True: ModelSetting.set('gdrive_user_auth', 'True')
            else: ModelSetting.set('gdrive_user_auth', 'False')
            ret = LibGdrive.user_authorize(ModelSetting.get('gdrive_token_path'))
            LogicBase.Services = LibGdrive.sa_authorize_for_multiple_connection(ModelSetting.get('gdrive_auth_path'), ModelSetting.get_int('gdrive_thread_num'))

            if LogicBase.RuleJobQueue == None: LogicBase.RuleJobQueue = py_queue.Queue()
            if LogicBase.RuleHandlerThread == None:
                LogicBase.RuleHandlerThread = list()
                for i in range(ModelSetting.get_int('gdrive_thread_num')):
                    LogicBase.RuleHandlerThread.append(threading.Thread(target=LogicBase.rule_handler_thread_function, args=(i,)))
                    LogicBase.RuleHandlerThread[i].daemon = True
                    LogicBase.RuleHandlerThread[i].start()

            if LogicBase.PlexScannerQueue is None: LogicBase.PlexScannerQueue = py_queue.Queue()
            if LogicBase.PlexScannerThread is None:
                LogicBase.PlexScannerThread = threading.Thread(target=LogicBase.plex_scanner_thread_function, args=())
                LogicBase.PlexScannerThread.daemon = True
                LogicBase.PlexScannerThread.start()

            if LogicBase.RemoveJobQueue is None: LogicBase.RemoveJobQueue = py_queue.Queue()
            if LogicBase.RemoveHandlerThread is None:
                LogicBase.RemoveHandlerThread = threading.Thread(target=LogicBase.remove_handler_thread_function, args=())
                LogicBase.RemoveHandlerThread.daemon = True
                LogicBase.RemoveHandlerThread.start()

            if LogicBase.ShortcutJobQueue is None: LogicBase.ShortcutJobQueue = py_queue.Queue()
            if LogicBase.ShortcutCreateThread is None:
                LogicBase.ShortcutCreateThread = threading.Thread(target=LogicBase.shortcut_create_thread_function, args=())
                LogicBase.ShortcutCreateThread.daemon = True
                LogicBase.ShortcutCreateThread.start()

            if ModelSetting.get_bool('tv_auto_start'):
                LogicBase.scheduler_start()

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return

    @staticmethod
    def task():
        try:
            service = LibGdrive.sa_authorize(ModelSetting.get('gdrive_auth_path'), return_service=True)
            if service == None:
                data = {'type':'warning', 'msg':u'서비스계정 인증에 실패하여 스케쥴러를 실행할 수 없습니다.'}
                socketio.emit("notify", data, namespace='/framework', broadcate=True)
                logger.error('[schedule]: failed to authorize sa accounts(%s)', ModelSetting.get('gdrive_auth_path'))
                return

            rule_items = ModelRuleItem.get_scheduled_entities()
            for rule in rule_items:
                logger.debug('[schedule] start search gdrive items(%s)', rule.name)
                count = 0
                rcount = 0
                if (rule.reserved == u'' or rule.reserved == None) and rule.max_depth > 1:
                    target_list = LibGdrive.get_target_subfolders(rule.root_folder_id, target_depth=rule.max_depth-1, service=service)
                    rule.reserved = json.dumps(target_list)
                    rule.save()

                # 최초 실행인 경우
                if rule.last_searched_time == None:
                    children = LibGdrive.get_all_subfolders(rule.root_folder_id, name=rule.name, max_depth=rule.max_depth, full_path=True, service=service)
                else:
                    children = []
                    if rule.max_depth > 1:
                        target_list = json.loads(rule.reserved)
                        #logger.debug(json.dumps(target_list, indent=2))
                        for folder in target_list['target_folders']:
                            tmp_children = LibGdrive.get_children_folders(folder['folder_id'], time_after=rule.last_searched_time, service=service)
                            children = children + tmp_children
                    else:
                        tmp_children = LibGdrive.get_children_folders(rule.root_folder_id, time_after=rule.last_searched_time, service=service)
                        children = children + tmp_children

                rule.last_searched_time = datetime.now()
                rule.save()
                logger.debug('[schedule] %s: %d 개의 새로운 항목이 조회됨', rule.name, len(children))
                for child in children:
                    name = child['name']
                    folder_id = child['folder_id'] if 'folder_id' in child else child['id']
                    parent_folder_id = child['parent_folder_id'] if 'parent_folder_id' in child else child['parents'][0]
                    mime_type = child['mime_type'] if 'mime_type' in child else child['mimeType']
                    logger.debug('%s,%s,%s', name, folder_id, parent_folder_id)

                    entity = None
                    entity = ScmUtil.get_entity_by_folder_id(rule.agent_type, folder_id)
                    if entity != None:
                        logger.debug(u'[schedule] SKIP: 이미 존재하는 아이템: %s', name)
                        rcount += 1
                        if rule.use_auto_create_shortcut and entity.shortcut_created == False and entity.excluded == False:
                            LogicBase.ShortcutJobQueue.put({'id':entity.id, 'agent_type':entity.agent_type})
                        continue

                    if rule.agent_type == 'ktv':
                        r = ScmUtil.search_ktv(name)
                        if r == None or r == {}:
                            r = ScmUtil.search_ktv_ott(name)
                            if r == None:
                                logger.error(u'[schedule] 메타정보 조회실패: %s:%s', rule.agent_type, name)
                                continue
                    else: 
                        r = ScmUtil.search_metadata(rule.agent_type, name)
                        if len(r) == 0:
                            git = guessit.guessit(name)
                            if 'year' in git: new_name = git['title'] + u' (' + str(git['year']) + u')'
                            else: new_name = git['title']
                            r = ScmUtil.search_metadata(rule.agent_type, new_name)
                            if len(r) == 0:
                                logger.error(u'[schedule] 메타정보 조회실패: %s:%s', rule.agent_type, name)
                                continue

                    ui_code = None # for av
                    if 'ui_code' in r: ui_code = r['ui_code']
                    info = ScmUtil.info_metadata(rule.agent_type, r['code'], r['title'])
                    if info == None:
                        logger.debug(u'메타정보 조회실패: %s:%s', rule.agent_type, r['title'])
                        continue

                    info['rule_name'] = rule.name
                    info['rule_id'] = rule.id
                    info['agent_type'] = rule.agent_type
                    info['root_folder_id'] = rule.root_folder_id
                    info['target_folder_id'] = rule.target_folder_id
                    info['name'] = name
                    info['mime_type'] = mime_type
                    info['folder_id'] = folder_id
                    info['parent_folder_id'] = parent_folder_id
                    gdrive_path = LibGdrive.get_gdrive_full_path(folder_id, service=service)
                    info['orig_gdrive_path'] = gdrive_path
                    if ui_code != None: info['ui_code'] = ui_code
                    if rule.agent_type.startswith('av'):
                        entity = ScmUtil.create_av_entity(info)
                    else:
                        entity = ScmUtil.create_tvmv_entity(info)
                    count += 1

                    if rule.use_auto_create_shortcut:
                        LogicBase.ShortcutJobQueue.put({'id':entity.id, 'agent_type':entity.agent_type})

                if rule.agent_type.startswith('av'): rule.item_count = ModelAvItem.get_item_count(rule.id)
                else: rule.item_count = ModelTvMvItem.get_item_count(rule.id)
                rule.save()
                data = {'type':'success', 'msg':u'경로규칙 <strong>"{n}"</strong>에 {c} 항목을 추가하였습니다.(중복:{r})'.format(n=rule.name, c=count, r=rcount)}
                socketio.emit("notify", data, namespace='/framework', broadcate=True)
                logger.debug('[schedule]: ended(name:%s, new: %d, skip: %d)', rule.name, count, rcount)

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_all_subfolders_group_by_parents(rule, service=None):
        try:
            folder_list = []
            target_list = json.loads(rule.reserved)
            for folder in target_list['target_folders']:
                folders = LibGdrive.get_all_subfolders(folder['folder_id'], name=folder['name'], service=service)
                folder_list = folder_list + folders
            return folder_list
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

        
    @staticmethod
    def rule_handler_thread_function(thread_id):
        logger.debug('(%d) rule_handler_thread: created', thread_id)
        while True:
            try:
                req = LogicBase.RuleJobQueue.get()
                service = LogicBase.Services[thread_id]
                rule_id = req['rule_id']
                logger.debug('(%d) rule_handler_thread: started(rule_id: %d)', thread_id, rule_id)

                count = 0
                rcount = 0
                rule = ModelRuleItem.get_by_id(rule_id)
                if rule.max_depth > 1:
                    target_list = LibGdrive.get_target_subfolders(rule.root_folder_id, target_depth=rule.max_depth-1, service = service)
                    rule.reserved = json.dumps(target_list)
                    rule.save()
                    folder_list = LogicBase.get_all_subfolders_group_by_parents(rule, service=service)
                else:
                    folder_list = LibGdrive.get_all_subfolders(rule.root_folder_id, name=rule.name, max_depth=rule.max_depth, service = service, full_path=True)

                rule.last_searched_time = datetime.now()
                for folder in folder_list:
                    name = folder['name']
                    folder_id = folder['folder_id']
                    parent_folder_id = folder['parent_folder_id']
                    mime_type = folder['mime_type']
                    logger.debug('%s,%s,%s', name, folder_id, parent_folder_id)

                    entity = None
                    entity = ScmUtil.get_entity_by_folder_id(rule.agent_type, folder_id)
                    if entity != None:
                        logger.debug(u'(%d) SKIP: 이미 존재하는 아이템: %s', thread_id, name)
                        rcount += 1
                        if rule.use_auto_create_shortcut and entity.shortcut_created == False and entity.excluded == False:
                            LogicBase.ShortcutJobQueue.put({'id':entity.id, 'agent_type':entity.agent_type})
                        continue

                    gdrive_path = LibGdrive.get_gdrive_full_path(folder_id)
                    #info = LogicBase.search_metadata(rule.agent_type, name)
                    if rule.agent_type == 'ktv':
                        r = ScmUtil.search_ktv(name)
                        if r == None or r == {}:
                            r = ScmUtil.search_ktv_ott(name)
                            if r == None:
                                logger.error(u'(%d) 메타정보 검색실패: %s:%s', thread_id, rule.agent_type, name)
                                continue
                    else: 
                        r = ScmUtil.search_metadata(rule.agent_type, name)
                        if len(r) == 0:
                            git = guessit.guessit(name)
                            if 'year' in git: new_name = git['title'] + u' (' + str(git['year']) + u')'
                            else: new_name = git['title']

                            r = ScmUtil.search_metadata(rule.agent_type, new_name)
                            if len(r) == 0:
                                logger.error(u'(%d) 메타정보 검색조회실패: %s:%s', thread_id, rule.agent_type, name)
                                continue
                            

                    #logger.debug(json.dumps(r, indent=2))
                    # for av
                    ui_code = None
                    if 'ui_code' in r: ui_code = r['ui_code']
                    #logger.debug('ui_code: %s', ui_code)

                    info = ScmUtil.info_metadata(rule.agent_type, r['code'], r['title'])
                    if info == None:
                        logger.debug(u'메타정보 조회실패: %s:%s', rule.agent_type, r['title'])
                        continue

                    info['rule_name'] = rule.name
                    info['rule_id'] = rule.id
                    info['agent_type'] = rule.agent_type
                    info['root_folder_id'] = rule.root_folder_id
                    info['target_folder_id'] = rule.target_folder_id
                    info['name'] = name
                    info['mime_type'] = mime_type
                    info['folder_id'] = folder_id
                    info['parent_folder_id'] = parent_folder_id
                    info['orig_gdrive_path'] = gdrive_path
                    if ui_code != None: info['ui_code'] = ui_code
                    if rule.agent_type.startswith('av'):
                        entity = ScmUtil.create_av_entity(info)
                    else:
                        entity = ScmUtil.create_tvmv_entity(info)
                    count += 1

                    if rule.use_auto_create_shortcut and entity.shortcut_created == False:
                        LogicBase.ShortcutJobQueue.put({'id':entity.id, 'agent_type':entity.agent_type})

                if rule.agent_type.startswith('av'): rule.item_count = ModelAvItem.get_item_count(rule.id)
                else: rule.item_count = ModelTvMvItem.get_item_count(rule.id)
                rule.save()
                data = {'type':'success', 'msg':u'경로규칙 <strong>"{n}"</strong>에 {c} 항목을 추가하였습니다.(중복:{r})'.format(n=rule.name, c=count, r=rcount)}
                socketio.emit("notify", data, namespace='/framework', broadcate=True)
                LogicBase.RuleJobQueue.task_done()
                logger.debug('rule_handler_thread: ended(name:%s, new: %d, skip: %d)', rule.name, count, rcount)

            except Exception as e:
                logger.debug('Exception:%s', e)
                logger.debug(traceback.format_exc())

    @staticmethod
    def plex_scanner_thread_function():
        from plex.model import ModelSetting as PlexModelSetting
        import plex
        logger.debug('plex_scanner_thread...started()')
        prev_section_id = -1
        while True:
            try:
                server = PlexModelSetting.get('server_url')
                token = PlexModelSetting.get('server_token')

                req = LogicBase.PlexScannerQueue.get()
                logger.debug('plex_scanner_thread...job-started()')

                item_id  = req['id']
                agent_type  = req['agent_type']
                queued_time= req['now']
                action = req['action']
                plex_path = req['path']

                section_id = plex.LogicNormal.get_section_id_by_filepath(plex_path)
                if section_id == -1:
                    logger.error('failed to get section_id by path(%s)', plex_path)
                    data = {'type':'warning', 'msg':'Plex경로오류! \"{p}\" 경로를 확인해 주세요'.format(p=plex_path)}
                    socketio.emit("notify", data, namespace='/framework', broadcate=True)
                    LogicBase.PlexScannerQueue.task_done()
                    continue

                logger.debug('스캔명령 전송: server(%s), token(%s), section_id(%s)', server, token, section_id)
                scan_path = py_urllib.quote(plex_path.encode('utf-8'))
                callback_id = '{}|{}|{}'.format(agent_type, str(item_id), action)
                if action == 'REFRESH': action = 'ADD'
                plex.Logic.send_scan_command2(package_name, section_id, scan_path, callback_id, action, package_name)
                LogicBase.PlexScannerQueue.task_done()
                logger.debug('plex_scanner_thread...job-end()')
            except Exception as e:
                logger.debug('Exception:%s', e)
                logger.debug(traceback.format_exc())


    @staticmethod
    def callback_handler(req):
        from plex.model import ModelSetting as PlexModelSetting
        import plex
        try:
            base_url = '{s}{m}?includeExternalMedia=1&X-Plex-Product=Plex%20Web&X-Plex-Product=Plex%20Web&X-Plex-Version=4.51.1&X-Plex-Platform=Chrome&X-Plex-Platform-Version=88.0&X-Plex-Sync-Version=2&X-Plex-Features=external-media%2Cindirect-media&X-Plex-Model=bundled&X-Plex-Device=Windows&X-Plex-Device-Name=Chrome&X-Plex-Device-Screen-Resolution=1920x937%2C1920x1080&X-Plex-Language=ko&X-Plex-Drm=widevine&X-Plex-Text-Format=plain&X-Plex-Provider-Version=1.3&X-Plex-Token={t}'
            server = PlexModelSetting.get('server_url')
            token = PlexModelSetting.get('server_token')
            devid = PlexModelSetting.get('machineIdentifier')
            agent_type,db_id,action = req['id'].split('|')
            filename = req['filename']
            logger.debug('[CALLBACK]: %s,%s,%s,%s', agent_type, db_id, action, filename)

            entity = None
            if agent_type.startswith('av'): entity = ModelAvItem.get_by_id(int(db_id))
            else: entity = ModelTvMvItem.get_by_id(int(db_id))

            if action == 'REFRESH':
                entity.updated_time = datetime.now()
                entity.save()
                logger.debug('[CALLBACK]: REFRESH done')
                return

            if action == 'ADD':
                if entity == None:
                    logger.error('[CALLBACK] ADD-failed to get entity(id:%s)', db_id)
                    return
                section_id = plex.LogicNormal.get_section_id_by_filepath(entity.plex_path)
                if section_id == -1:
                    logger.error('[CALLBACK] ADD-failed to get plex section_id(path:%s)', entity.plex_path)
                    return

                ret = plex.LogicNormal.find_by_filename_part(entity.plex_path)
                metadata_id = ''
                #logger.debug(ret['ret'])
                #logger.debug(json.dumps(ret, indent=2))

                # get metakey like '/library/metadata/519'
                if ret['ret'] == True:
                    for item in ret['list']:
                        if item['dir'] == entity.plex_path:
                            metadata_id = item['metadata_id']
                            break
                if metadata_id == '':
                    logger.error('[CALLBACK] ADD-failed to get metadata_id(path:%s)', entity.plex_path)
                    return

                # SHOW의 경우 프로그램 자체의 메타데이터 얻어옴(에피소드> 시즌> 프로그램)
                if agent_type == 'ktv' or agent_type == 'ftv':
                    metadata_id = ScmUtil.get_program_metadata_id(metadata_id)

                logger.debug("[CALLBACK] ADD-sectiond_id: s, metadata_id: %s", section_id, metadata_id)
                entity.plex_section_id = str(section_id)
                entity.plex_metadata_id = str(metadata_id)
                entity.save()
                return

            ### REMOVE
            if ModelSetting.get_bool('plex_remove_library') == False: return
            # 일괄삭제 등으로 entity가 존재하지 않는 경우 처리
            if entity == None:
                ret = plex.LogicNormal.find_by_filename_part(filename)
                metadata_id = ''
                if ret['ret'] == True:
                    for item in ret['list']:
                        if item['dir'] == filename:
                            metadata_id = item['metadata_id']
                            break
                if metadata_id == '':
                    logger.error('[CALLBACK] REMOVE-failed to get metadata_id(path:%s)', filename)
                    return
                if agent_type == 'ktv' or agent_type == 'ftv':
                    metadata_id = ScmUtil.get_program_metadata_id(metadata_id)

                if plex.LogicNormal.os_path_exists(filename) == False: # 존재하지 않는 경우만 삭제
                    url = base_url.format(s=server, m=metadata_id, t=token, d=devid)
                    headers = { "Accept": 'application/json',
                            "Accept-Encoding": 'gzip, deflate, br',
                            "Accept-Language": 'ko',
                            "Connection": 'keep-alive',
                            "User-Agent": 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.182 Mobile Safari/537.36' }
    
                    res = requests.delete(url, headers=headers)
                    logger.debug('[CALLBACK] REMOVE-Response Status Code: %s', res.status_code)

                    if res.status_code != 200:
                        logger.error('[CALLBACK] REMOVE-failed to delete metadata(%s,%s)', metadata_id, filename)
                return

            # ADD시 CALL이 스캔전에 도착한 경우 처리
            if entity.plex_metadata_id == "" or entity.plex_metadata_id == None:
                section_id = plex.LogicNormal.get_section_id_by_filepath(entity.plex_path)
                if section_id == -1:
                    logger.error('[CALLBACK] REMOVE-failed to get plex section_id(path:%s)', entity.plex_path)
                    return

                ret = plex.LogicNormal.find_by_filename_part(entity.plex_path)
                metadata_id = ''
                if ret['ret'] == True:
                    for item in ret['list']:
                        if item['dir'] == entity.plex_path:
                            metadata_id = item['metadata_id']
                            break
                if metadata_id == '':
                    logger.error('[CALLBACK] REMOVE-failed to get metadata_id(path:%s)', entity.plex_path)
                    return

                if agent_type == 'ktv' or agent_type == 'ftv':
                    metadata_id = ScmUtil.get_program_metadata_id(metadata_id)

                logger.debug("[CALLBACK] REMOVE-sectiond_id: s, metadata_id: %s", section_id, metadata_id)
                entity.plex_section_id = section_id
                entity.plex_metadata_id = metadata_id

            if plex.LogicNormal.os_path_exists(entity.plex_path) == False: # 존재하지 않는 경우만 삭제
                metadata_id = entity.plex_metadata_id
                url = base_url.format(s=server, m=metadata_id, t=token, d=devid)
                headers = { "Accept": 'application/json',
                        "Accept-Encoding": 'gzip, deflate, br',
                        "Accept-Language": 'ko',
                        "Connection": 'keep-alive',
                        "User-Agent": 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.182 Mobile Safari/537.36' }

                res = requests.delete(url, headers=headers)
                logger.debug('[CALLBACK] REMOVE-Response Status Code: %s', res.status_code)

                if res.status_code != 200:
                    logger.error('[CALLBACK] REMOVE-failed to delete metadata(%s,%s)', entity.metadata_id, filename)
                    return;

                entity.plex_path = u''
                entity.gdrive_path = u''
                entity.local_path = u''
                entity.plex_section_id = u''
                entity.plex_metadata_id = u''
                entity.save()
                return
            else:
                logger.error('[CALLBACK] REMOVE-file still exists(%s)', entity.plex_path)
                return
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def shortcut_create_thread_function():
        logger.debug('shortcut_create_thread_function...started()')
        _map = {'ktv':'tv','ftv':'tv','movie':'mv','avdvd':'av','avama':'av'}
        while True:
            try:
                req = LogicBase.ShortcutJobQueue.get()
                logger.debug('shortcut_create_thread_function...job-started()')
                db_id  = req['id']
                module_name = req['module_name'] if 'module_name' in req else _map[req['agent_type']]
                LogicBase.create_shortcut(module_name, db_id)
                LogicBase.ShortcutJobQueue.task_done()
                logger.debug('shortcut_create_thread_function...job-end()')
            except Exception as e:
                logger.debug('Exception:%s', e)
                logger.debug(traceback.format_exc())
                LogicBase.RemoveJobQueue.task_done()



    @staticmethod
    def remove_handler_thread_function():
        logger.debug('remove_handler_thread_function...started()')
        _map = {'ktv':'tv','ftv':'tv','movie':'mv','avdvd':'av','avama':'av'}
        while True:
            try:
                req = LogicBase.RemoveJobQueue.get()
                logger.debug('remove_handler_thread_function...job-started()')

                item_id  = req['id']
                target  = req['target']
                module_name = req['module_name'] if 'module_name' in req else _map[req['agent_type']]

                if target == 'shortcut':
                    ret = LogicBase.remove_shortcut(module_name, item_id)
                    if ret['ret'] != 'success':
                        data = {'type':'warning', 'msg':'바로가기 삭제실패{m:id}'.format(m=module_name, id=item_id)}
                        socketio.emit('notify', data, namespace='/framework', broadcast=True)
                elif target == 'shortcut_remove_done':
                    rule = ModelRuleItem.get_by_id(item_id)
                    data = {'type':'success', 'msg':'"{r}"의 모든 바로가기를 삭제하였습니다'.format(r=rule.name)}
                    socketio.emit('notify', data, namespace='/framework', broadcast=True)
                    rule.shortcut_count = 0
                    rule.save()
                elif target == 'items':
                    rule = ModelRuleItem.get_by_id(item_id)
                    if module_name == 'av': ModelAvItem.delete_items_by_rule_id(item_id)
                    else: ModelTvMvItem.delete_items_by_rule_id(item_id)
                    data = {'type':'success', 'msg':'"{r}"의 모든 아이템을 삭제하였습니다'.format(r=rule.name)}
                    socketio.emit('notify', data, namespace='/framework', broadcast=True)
                elif target == 'rule':
                    rule = ModelRuleItem.get_by_id(item_id)
                    if module_name == 'av': count = ModelAvItem.get_item_count(item_id)
                    else: count = ModelTvMvItem.get_item_count(item_id)
                    if count == 0: 
                        data = {'type':'success', 'msg':'경로규칙 "{r}"를 삭제하였습니다'.format(r=rule.name)}
                        ModelRuleItem.delete(item_id)
                    socketio.emit('notify', data, namespace='/framework', broadcast=True)

                LogicBase.RemoveJobQueue.task_done()
                logger.debug('remove_handler_thread_function...job-end()')
            except Exception as e:
                logger.debug('Exception:%s', e)
                logger.debug(traceback.format_exc())
                LogicBase.RemoveJobQueue.task_done()

    @staticmethod
    def create_shortcut(module_name, db_id):
        try:
            if module_name == "av": entity = ModelAvItem.get_by_id(db_id)
            else: entity = ModelTvMvItem.get_by_id(db_id)
            shortcut_name = ScmUtil.get_shortcut_name(entity)
            logger.debug('create_shortcut: title(%s), shortcut(%s)', entity.title, shortcut_name)

            parent_folder_id = entity.target_folder_id
            rule = ModelRuleItem.get_by_id(entity.rule_id)
            if rule.use_subfolder:
                rule_str = rule.subfolder_rule
                parent_folder_id = ScmUtil.create_subfolder(rule_str, entity)
                if parent_folder_id == None:
                    logger.error(u'하위폴더 생성에 실패:경로규칙에 지정된 타겟폴더에 바로가기 생성')
                    parent_folder_id = entity.target_folder_id

            ret = LibGdrive.create_shortcut(shortcut_name, entity.folder_id, parent_folder_id)
            if ret['ret'] != 'success':
                logger.error('failed to create shortcut')
                return { 'ret':'error', 'msg':'생성실패! 로그를 확인해주세요.' }

            shortcut = ret['data']
            # entity update
            entity.shortcut_created = True
            entity.shortcut_folder_id = py_unicode(shortcut['id'])
            entity.target_folder_id = parent_folder_id
            entity.gdrive_path = LibGdrive.get_gdrive_full_path(entity.shortcut_folder_id)
            entity.plex_path = ScmUtil.get_plex_path(entity.gdrive_path)
            entity.local_path = ScmUtil.get_local_path(entity.gdrive_path)
            logger.debug('gdpath(%s),plexpath(%s)', entity.gdrive_path, entity.plex_path)
            entity.save()

            rule.shortcut_count = rule.shortcut_count + 1
            rule.save()

            logger.debug(u'바로가기 생성완료(%s)', entity.shortcut_folder_id)
            ret = { 'ret':'success', 'msg':'바로가기 생성 성공{n}'.format(n=entity.name) }

            if rule.use_plex:
                LogicBase.PlexScannerQueue.put({'id':entity.id, 'agent_type':entity.agent_type, 'path':entity.plex_path, 'action':'ADD', 'now':datetime.now()})
                ret = { 'ret':'success', 'msg':'바로가기 생성 성공{n}, 스캔명령 전송대기'.format(n=entity.name) }
            return ret

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'생성실패! 로그를 확인해주세요.' }


    @staticmethod
    def remove_handler(req):
        try:
            target = req.form['target']
            rule_id = int(req.form['id'])
            rule = ModelRuleItem.get_by_id(rule_id)
            item_count = rule.item_count
            shortcut_count = rule.shortcut_count
            if target == 'rule':
                LogicBase.remove_all_shortcuts(rule_id)
                LogicBase.remove_all_items(rule_id)
                LogicBase.remove_rule(rule_id)
                ret = {'ret':'success', 'msg':'{i}개의 아이템,{s}개의 바로가기 삭제 요청완료'.format(i=item_count, s=shortcut_count) }
            elif target == 'item':
                LogicBase.remove_all_items(rule_id)
                ret = {'ret':'success', 'msg':'{i}개의 아이템 삭제 요청완료'.format(i=item_count) }
            elif target == 'shortcut':
                LogicBase.remove_all_shortcuts(rule_id)
                ret = {'ret':'success', 'msg':'{s}개의 바로가기 삭제 요청완료'.format(s=shortcut_count) }
            return ret
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())


    @staticmethod
    def remove_rule(rule_id):
        try:
            rule = ModelRuleItem.get_by_id(rule_id)
            req = {}
            req['agent_type'] = rule.agent_type
            req['target'] = 'rule'
            req['id'] = rule_id
            LogicBase.RemoveJobQueue.put(req)
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def remove_all_items(rule_id):
        try:
            rule = ModelRuleItem.get_by_id(rule_id)
            req = {}
            req['agent_type'] = rule.agent_type
            req['target'] = 'items'
            req['id'] = rule_id
            LogicBase.RemoveJobQueue.put(req)
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def remove_all_shortcuts(rule_id):
        try:
            rule = ModelRuleItem.get_by_id(rule_id)
            if rule.agent_type.startswith('av'):
                entities = ModelAvItem.get_shortcut_created_entities(rule.id)
            else: #tv,mv
                entities = ModelTvMvItem.get_shortcut_created_entities(rule.id)

            for entity in entities:
                req = {}
                req['agent_type'] = entity.agent_type
                req['id'] = entity.id
                req['target'] = 'shortcut'
                LogicBase.RemoveJobQueue.put(req)

            req = {}
            req['agent_type'] = rule.agent_type
            req['id'] = rule_id
            req['target'] = 'shortcut_remove_done'
            LogicBase.RemoveJobQueue.put(req)

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())


    @staticmethod
    def remove_shortcut(module_name, db_id):
        try:
            if module_name == 'av': entity = ModelAvItem.get_by_id(db_id)
            else: entity = ModelTvMvItem.get_by_id(db_id)
            logger.debug('remove_shortcut: title(%s), shortcut(%s)', entity.title, os.path.basename(entity.plex_path))

            if ModelSetting.get_bool('use_trash'):
                trash_folder_id = ModelSetting.get('trash_folder_id')
                finfo = LibGdrive.get_file_info(trash_folder_id)
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
                LogicBase.PlexScannerQueue.put({'id':entity.id, 'agent_type':entity.agent_type, 'path':entity.plex_path, 'action':'REMOVE', 'now':datetime.now()})
                ret = { 'ret':'success', 'msg':'바로가기 삭제 성공{n}, 스캔명령 전송대기'.format(n=entity.name) }
            return ret

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def scheduler_start():
        try:
            from .logic_tv import LogicTv
            if not scheduler.is_include('scmanger_tv'):
                interval = ModelSetting.get('tv_interval')
                job = Job(package_name, 'scmanager_tv', interval, LogicTv(LogicTv).scheduler_function, u"방영중 TV 에피소트 추가", True)
                scheduler.add_job_instance(job)
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def scheduler_stop():
        try:
            scheduler.remove_job('scmanager_tv')
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


