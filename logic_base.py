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
        'use_av'     : 'False',
        # API
        'gdrive_token_path' : os.path.join(path_data, package_name, 'token.pickle'),
        'gdrive_creds_path' : os.path.join(path_data, package_name, 'credentials.json'),
        'gdrive_sa_auth' : u'False',
        'gdrive_user_auth' : u'False',
        'gdrive_auth_code' : u'',

        # 일반
        'gdrive_auth_path' : os.path.join(path_data, 'rclone_expand', 'accounts'),
        'gdrive_auto_start' : u'False',
        'gdrive_interval' : u'60',
        'gdrive_root_folder_id' : u'',
        'gdrive_category_rules' : u'',
        'gdrive_plex_path_rule': u'/UserPMS/orial|/mnt/plex',
        'gdrive_local_path_rule': u'/UserPMS/orial|/mnt/plex',
        'avlist_show_poster': u'True',
        'use_trash': u'False',
        'trash_folder_id': u'',

        # plex
        'plex_scan_delay': u'30',
        'plex_scan_min_limit': u'10',

        # for ktv
        'ktv_meta_result_limit_per_site': u'3',
        'ktv_use_season_folder': u'True',
        'ktv_shortcut_name_rule': '{title} ({year})',

        # for ftv
        'ftv_use_season_folder': u'True',
        'ftv_shortcut_name_rule': u'{title} ({year})',

        # for movie
        'movie_shortcut_name_rule': u'{title} ({year})',

        # for avdvd
        'avdvd_shortcut_name_rule': u'{code}',

        # for avama
        'avama_shortcut_name_rule': u'{code}',
    }

    RuleHandlerThread = None
    RuleJobQueue = None

    PlexScannerThread = None
    PlexScannerQueue = None


    def __init__(self, P):
        super(LogicBase, self).__init__(P, 'setting')
        self.name = 'base'

    def plugin_load(self):
        self.initialize()

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        P.logger.debug('sub:%s', sub)
        if sub == 'setting':
            job_id = '%s_%s' % (self.P.package_name, self.name)
            arg['scheduler'] = str(scheduler.is_include(job_id))
            arg['is_running'] = str(scheduler.is_running(job_id))
            arg['use_av'] = ModelSetting.get_bool('use_av')
        elif sub == 'rulelist':
            arg['categories'] = ','.join(ScmUtil.get_rule_names(self.name))
            arg['agent_types'] = ','.join(ScmUtil.get_all_agent_types())
            arg['use_av'] = ModelSetting.get_bool('use_av')
        return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)

    def process_ajax(self, sub, req):
        try:
            ret = {'ret':'success', 'list':[]}
            logger.debug('BASE-AJAX %s', sub)
            logger.debug(req.form)

            if sub == 'rule_list':
                ret = ModelRuleItem.web_list(req)
            elif sub == 'get_gdrive_path':
                folder_id = req.form['folder_id']
                gdrive_path = LibGdrive.get_gdrive_full_path(folder_id)
                logger.debug('gdrive_path: %s', gdrive_path)
                return jsonify({'ret':'success', 'data':gdrive_path})
            elif sub == 'register_rule':
                logger.debug(req.form)
                ret = ScmUtil.register_rule(req)
                return jsonify(ret)
            elif sub == 'execute_rule':
                rule_id = int(req.form['id'])
                req = {'rule_id': rule_id}
                LogicBase.RuleJobQueue.put(req)
                ret = {'ret':'success', 'msg':'실행요청 완료'}
                return jsonify(ret)
            elif sub == 'modify_rule':
                logger.debug(req.form)
                ret = ScmUtil.modify_rule(req)
                return jsonify(ret)
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
            elif sub == 'sa_auth':
                json_path = req.form['path']
                ret = LibGdrive.sa_authorize(json_path)
                if ret == True: ModelSetting.set('gdrive_auth_path', json_path)
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
    def initialize():
        try:
            if LogicBase.RuleJobQueue == None: LogicBase.RuleJobQueue = py_queue.Queue()
            if LogicBase.RuleHandlerThread == None:
                LogicBase.RuleHandlerThread = threading.Thread(target=LogicBase.rule_handler_thread_function, args=())
                LogicBase.RuleHandlerThread.daemon = True
                LogicBase.RuleHandlerThread.start()

            if LogicBase.PlexScannerQueue is None: LogicBase.PlexScannerQueue = py_queue.Queue()
            if LogicBase.PlexScannerThread is None:
                LogicBase.PlexScannerThread = threading.Thread(target=LogicBase.plex_scanner_thread_function, args=())
                LogicBase.PlexScannerThread.daemon = True
                LogicBase.PlexScannerThread.start()

            json_path = ModelSetting.get('gdrive_auth_path')
            if not os.path.exists(json_path):
                logger.error('can not recognize gdrive_auth_path(%s)', json_path)
                data = {'type':'warning', 'msg':'인증파일(.json) 경로를 확인해주세요.'}
                socketio.emit('notify', data, namespace='/framework', broadcast=True)
                return

            ret = LibGdrive.sa_authorize(json_path)
            if ret == True: ModelSetting.set('gdrive_sa_auth', 'True')
            else: ModelSetting.set('gdrive_sa_auth', 'False')
            ret = LibGdrive.user_authorize(ModelSetting.get('gdrive_token_path'))
            if ret == True: ModelSetting.set('gdrive_user_auth', 'True')
            else: ModelSetting.set('gdrive_user_auth', 'False')

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return

    @staticmethod


    @staticmethod
    @celery.task
    def task():
        try:
            rule_items = ModelRuleItem.get_scheduled_entities()
            for rule in rule_items:
                folder_list = LibGdrive.get_all_folders(rule.root_folder_id, rule.last_searched_time)
                rule.last_searched_time = datetime.now()
                for folder in folder_list:
                    name = folder['name']
                    folder_id = folder['folder_id']
                    parent_folder_id = folder['parent_folder_id']
                    mime_type = folder['mime_type']
                    logger.debug('[schedule] %s,%s,%s,%s', name, folder_id, mime_type, parent_folder_id)
                    entity = None
                    entity = ModelTvMvItem.get_by_folder_id(folder_id)
                    if entity != None and entity.parent_folder_id == r['parent']:
                        logger.debug(u'SKIP: 이미 존재하는 아이템: %s', r['name'])
                        continue

                    title, year = LogicBase.get_title_year_from_dname(name)
                    r = ScmUtil.search_metadata(rule.agent_type, name)
                    if len(r) == 0:
                        logger.debug(u'메타정보 조회실패: %s:%s', rule.agent_type, r['name'])
                        continue

                    info = ScmUtil.info_metadata(rule.agent_type, r['code'], r['title'])
                    if info == None:
                        logger.debug(u'메타정보 조회실패: %s:%s', rule.agent_type, r['title'])
                        continue
                    info['rule_name'] = rule.name
                    info['rule_id'] = rule.id
                    info['agent_type'] = rule.agent_type
                    info['root_folder_id'] = rule.root_folder_id
                    info['target_folder_id'] = rule.target_folder_id
                    info['name'] = r['name']
                    info['mime_type'] = r['mimeType']
                    info['folder_id'] = r['id']
                    info['parent_folder_id'] = r['parent']
                    entity = ScmUtil.create_tvmv_entity(info)
                    rule.item_count += 1

                rule.save()

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def rule_handler_thread_function():
        while True:
            try:
                req = LogicBase.RuleJobQueue.get()
                rule_id = req['rule_id']
                logger.debug('rule_handler_thread: started(rule_id: %d)', rule_id)

                count = 0
                rcount = 0
                rule = ModelRuleItem.get_by_id(rule_id)
                #tree = LogicBase.get_all_subfolders(rule.root_folder_id, name=rule.name, max_depth=rule.max_depth)
                folder_list = LibGdrive.get_all_subfolders(rule.root_folder_id, name=rule.name, max_depth=rule.max_depth)
                rule.last_searched_time = datetime.now()
                for folder in folder_list:
                    name = folder['name']
                    folder_id = folder['folder_id']
                    parent_folder_id = folder['parent_folder_id']
                    mime_type = folder['mime_type']
                    gdrive_path = folder['full_path']
                    logger.debug('%s,%s,%s,%s,%s', name, folder_id, mime_type, parent_folder_id, gdrive_path)

                    entity = None
                    entity = ScmUtil.get_entity_by_folder_id(rule.agent_type, folder_id)
                    if entity != None:
                        logger.debug(u'SKIP: 이미 존재하는 아이템: %s', name)
                        rcount += 1
                        continue

                    #info = LogicBase.search_metadata(rule.agent_type, name)
                    if rule.agent_type == 'ktv':
                        r = ScmUtil.search_ktv(name)
                        if r == None or r == {}:
                            r = ScmUtil.search_ktv_ott(name)
                            if r == None:
                                logger.error(u'메타정보 조회실패: %s:%s', rule.agent_type, name)
                                continue
                    else: 
                        r = ScmUtil.search_metadata(rule.agent_type, name)
                        if len(r) == 0:
                            git = guessit.guessit(name)
                            if 'year' in git: new_name = git['title'] + u' (' + str(git['year']) + u')'
                            else: new_name = git['title']

                            r = ScmUtil.search_metadata(rule.agent_type, new_name)
                            if len(r) == 0:
                                logger.error(u'메타정보 조회실패: %s:%s', rule.agent_type, name)
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

                if rule.agent_type.startswith('av'): rule.item_count = ModelAvItem.get_item_count(rule.id)
                else: rule.item_count = ModelTvMvItem.get_item_count(rule.id)
                rule.save()
                data = {'type':'success', 'msg':u'경로규칙 <strong>"{n}"</strong>에 {c} 항목을 추가하였습니다.(중복:{r})'.format(n=rule.name, c=count, r=rcount)}
                socketio.emit("notify", data, namespace='/framework', broadcate=True)
                LogicBase.RuleJobQueue.task_done()
                logger.debug('rule_handler_thread: ended(name:%s, new: %d, skip: %d)', rule.name, count, rcount)
                time.sleep(1)

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
                #TODO
                scan_delay = ModelSetting.get_int('plex_scan_delay')
                scan_min_limit = ModelSetting.get_int('plex_scan_min_limit')

                req = LogicBase.PlexScannerQueue.get()
                now = datetime.now()
                logger.debug('plex_scanner_thread...job-started()')

                item_id  = req['id']
                agent_type  = req['agent_type']
                queued_time= req['now']
                action = req['action']

                if agent_type.startswith('av'): entity = ModelAvItem.get_by_id(item_id)
                else: entity = ModelTvMvItem.get_by_id(item_id)
                #plex_path = os.path.dirname(entity.plex_path)
                #section_id = plex.LogicNormal.get_section_id_by_filepath(plex_path)
                section_id = plex.LogicNormal.get_section_id_by_filepath(entity.plex_path)
                if section_id == -1:
                    logger.error('failed to get section_id by path(%s)', plex_path)
                    data = {'type':'warning', 'msg':'Plex경로오류! \"{p}\" 경로를 확인해 주세요'.format(p=entity.plex_path)}
                    socketio.emit("notify", data, namespace='/framework', broadcate=True)
                    LogicBase.PlexScannerQueue.task_done()
                    continue

                timediff = queued_time + timedelta(seconds=scan_delay) - now
                delay = int(timediff.total_seconds())
                if delay < 0: delay = 0
                if delay < scan_min_limit and prev_section_id == section_id: 
                    logger.debug('스캔명령 전송 스킵...(%d)s', delay)
                    LogicBase.PlexScannerQueue.task_done()
                    continue

                logger.debug('스캔명령 전송 대기...(%d)s', delay)
                time.sleep(delay)

                logger.debug('스캔명령 전송: server(%s), token(%s), section_id(%s)', server, token, section_id)
                scan_path = py_urllib.quote(entity.plex_path.encode('utf-8'))
                callback_id = '{}|{}|{}'.format(agent_type, str(entity.id), action)
                plex.Logic.send_scan_command2(package_name, section_id, scan_path, callback_id, action, package_name)


                """
                url = '{server}/library/sections/{section_id}/refresh?X-Plex-Token={token}'.format(server=server, section_id=section_id, token=token)
                res = requests.get(url)
                if res.status_code == 200:
                    prev_section_id = section_id
                    logger.debug('스캔명령 전송 완료: %s', entity.plex_path)
                    data = {'type':'success', 'msg':'아이템({p}) 추가/스캔요청 완료.'.format(p=entity.plex_path)}
                else:
                    logger.error('스캔명령 전송 실패: %s', entity.plex_path)
                    data = {'type':'warning', 'msg':'스캔명령 전송 실패! 로그를 확인해주세요'}
                socketio.emit("notify", data, namespace='/framework', broadcate=True)
                """
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

            if agent_type.startswith('av'): entity = ModelAvItem.get_by_id(int(db_id))
            else: entity = ModelTvMvItem.get_by_id(int(db_id))

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

            # REMOVE
            if plex.LogicNormal.os_path_exists(entity.plex_path) == False: # 존재하지 않는 경우만 삭제
                metadata_id = entity.plex_metadata_id
                url = base_url.format(s=server, m=metadata_id, t=token, d=devid)
                headers = { "Accept": 'application/json',
                        "Accept-Encoding": 'gzip, deflate, br',
                        "Accept-Language": 'ko',
                        "Connection": 'keep-alive',
                        #"sec-ch-ua": 'Chromium";v="88", "Google Chrome";v="88", ";Not\\A\"Brand";v="99',
                        #"Sec-Fetch-Dest": 'empty',
                        #"Sec-Fetch-Mode": 'cors',
                        #"Sec-Fetch-Site": 'cross-site',
                        #'X-Plex-Device': 'Windows',
                        #'X-Plex-Device-Name': 'Chrome',
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

