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

# googledrive api
try:
    from oauth2client.service_account import ServiceAccountCredentials
except:
    os.system("{} install oauth2client".format(app.config['config']['pip']))
    from oauth2client.service_account import ServiceAccountCredentials

try:
    from googleapiclient.discovery import build
except:
    os.system("{} install googleapiclient".format(app.config['config']['pip']))
    from googleapiclient.discovery import build

# anytree
try:
    from anytree import Node, PreOrderIter
except:
    os.system("{} install anytree".format(app.config['config']['pip']))
    from anytree import Node, PreOrderIter

# 패키지
from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

# 전역변수
service     = None
json_list   = []

#########################################################

class LogicGdrive(LogicModuleBase):
    from .logic_av import LogicAv
    db_default = {
        # 일반
        'gdrive_auth_path' : u'/app/data/rclone_expand/accounts',
        'gdrive_auto_start' : 'False',
        'gdrive_interval' : u'60',
        'gdrive_root_folder_id' : u'',
        'gdrive_category_rules' : u'',
        'gdrive_plex_path_rule': u'/UserPMS/orial|/mnt/plex',

        # plex
        'plex_scan_delay': u'30',
        'plex_scan_min_limit': u'10',

        # for ktv
        'ktv_meta_result_limit_per_site': '3',
        'ktv_use_season_folder': 'True',
        'ktv_shortcut_name_rule': '{title} ({year})',

        # for ftv
        'ftv_use_season_folder': 'True',
        'ftv_shortcut_name_rule': '{title} ({year})',

        # for movie
        'movie_shortcut_name_rule': '{title} ({year})',

        # for avdvd
        'avdvd_shortcut_name_rule': '{code}',

        # for avama
        'avama_shortcut_name_rule': '{code}',
    }

    RuleHandlerThread = None
    RuleJobQueue = None

    PlexScannerThread = None
    PlexScannerQueue = None


    def __init__(self, P):
        super(LogicGdrive, self).__init__(P, 'setting')
        self.name = 'gdrive'

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
        elif sub == 'itemlist':
            arg['categories'] = ','.join(LogicGdrive.get_rule_names())
            arg['agent_types'] = ','.join(LogicGdrive.get_agent_types())
        return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)

    def process_ajax(self, sub, req):
        try:
            ret = {'ret':'success', 'list':[]}
            logger.debug('GD-AJAX %s', sub)
            logger.debug(req.form)

            if sub == 'rule_list':
                ret = ModelRuleItem.web_list(req)
            elif sub == 'get_gdrive_path':
                folder_id = req.form['folder_id']
                gdrive_path = LogicGdrive.get_gdrive_full_path(folder_id)
                logger.debug('gdrive_path: %s', gdrive_path)
                return jsonify({'ret':'success', 'data':gdrive_path})
            elif sub == 'register_rule':
                logger.debug(req.form)
                ret = LogicGdrive.register_rule(req)
                return jsonify(ret)
            elif sub == 'execute_rule':
                rule_id = int(req.form['id'])
                req = {'rule_id': rule_id}
                LogicGdrive.RuleJobQueue.put(req)
                ret = {'ret':'success', 'msg':'실행요청 완료'}
                return jsonify(ret)
            elif sub == 'modify_rule':
                logger.debug(req.form)
                ret = LogicGdrive.modify_rule(req)
                return jsonify(ret)
            elif sub == 'web_list':
                ret = ModelGdriveItem.web_list(req)
            elif sub == 'create_shortcut':
                entity_id = int(req.form['id'])
                ret = LogicGdrive.create_shortcut(entity_id)
            elif sub == 'metadata_search':
                agent_type = req.form['meta_agent_type']
                title = req.form['meta_search_word']
                ret = LogicGdrive.search_metadata(agent_type, title, get_list=True)
            elif sub == 'apply_meta':
                logger.debug(req.form)
                ret = LogicGdrive.apply_meta(req)
            elif sub == 'refresh_info':
                entity_id = int(req.form['id'])
                ret = LogicGdrive.refresh_info(entity_id)

            return jsonify(ret)

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})

    def scheduler_function(self):
        logger.debug('scheduler function!!!!!!!!!!!!!!')
        if app.config['config']['use_celery']:
            result = LogicGdrive.task.apply_async()
            result.get()
        else:
            LogicGdrive.task()

    #########################################################
    @staticmethod
    def initialize():
        global service, json_list

        if LogicGdrive.RuleJobQueue == None: LogicGdrive.RuleJobQueue = py_queue.Queue()
        if LogicGdrive.RuleHandlerThread == None:
            LogicGdrive.RuleHandlerThread = threading.Thread(target=LogicGdrive.rule_handler_thread_function, args=())
            LogicGdrive.RuleHandlerThread.daemon = True
            LogicGdrive.RuleHandlerThread.start()

        if LogicGdrive.PlexScannerQueue is None: LogicGdrive.PlexScannerQueue = py_queue.Queue()
        if LogicGdrive.PlexScannerThread is None:
            LogicGdrive.PlexScannerThread = threading.Thread(target=LogicGdrive.plex_scanner_thread_function, args=())
            LogicGdrive.PlexScannerThread.daemon = True
            LogicGdrive.PlexScannerThread.start()

        json_path = ModelSetting.get('gdrive_auth_path')
        if not os.path.exists(json_path):
            logger.error('can not recognize gdrive_auth_path(%s)', json_path)
            data = {'type':'warning', 'msg':'인증파일(.json) 경로를 확인해주세요.'}
            socketio.emit('notify', data, namespace='/framework', broadcast=True)
            return

        if os.path.isdir(json_path):
            json_list = LogicGdrive.get_all_jsonfiles(json_path)
            logger.debug('load json list(%d)', len(json_list))
            json_file = ''.join(random.sample(json_list, 1))
        else:
            json_file = json_path
            json_list = [json_path]

        logger.debug('json_file: %s', json_file)

        scope = ['https://www.googleapis.com/auth/drive']
        try:
            credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file, scope)
            service = build('drive', 'v3', credentials=credentials)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def switch_service_account():
        global service, json_list
        while True:
            try:
                scope = ['https://www.googleapis.com/auth/drive']
                json_file = ''.join(random.sample(json_list, 1))
                credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file, scope)
                service = build('drive', 'v3', credentials=credentials)
                return service
            except Exception as e: 
                logger.error('Exception:%s', e)
                logger.error(traceback.format_exc())
                if len(json_list) == 1: return None

    @staticmethod
    @celery.task
    def task():
        try:
            rule_items = ModelRuleItem.get_scheduled_entities()
            for rule in rule_items:
                tree = LogicGdrive.get_all_folders(rule.root_folder_id, rule.last_searched_time)
                rule.last_searched_time = datetime.now()
                for node in PreOrderIter(tree, filter_=lambda n:n.height == 0):
                    name = node.name
                    folder_id = node.id
                    parent_folder_id = node.parent_id
                    mime_type = node.mime_type
                    logger.debug('[schedule] %s,%s,%s,%s', name, folder_id, mime_type, parent_folder_id)
                    entity = None
                    entity = ModelGdriveItem.get_by_folder_id(folder_id)
                    if entity != None and entity.parent_folder_id == r['parent']:
                        logger.debug(u'SKIP: 이미 존재하는 아이템: %s', r['name'])
                        continue

                    title, year = LogicGdrive.get_title_year_from_dname(name)
                    r = LogicGdrive.search_metadata(rule.agent_type, name)
                    if len(r) == 0:
                        logger.debug(u'메타정보 조회실패: %s:%s', rule.agent_type, r['name'])
                        continue

                    info = LogicGdrive.info_metadata(rule.agent_type, r['code'], r['title'])
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
                    entity = LogicGdrive.create_gd_entity(info)
                    rule.item_count += 1

                rule.save()

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def rule_handler_thread_function():
        while True:
            try:
                global service, json_list
                #if service == None: LogicGdrive.initialize()

                req = LogicGdrive.RuleJobQueue.get()
                rule_id = req['rule_id']
                logger.debug('rule_handler_thread: started(rule_id: %d)', rule_id)

                count = 0
                rcount = 0
                rule = ModelRuleItem.get_by_id(rule_id)
                tree = LogicGdrive.get_all_subfolders(rule.root_folder_id, name=rule.name, max_depth=rule.max_depth)
                rule.last_searched_time = datetime.now()
                for node in PreOrderIter(tree, filter_=lambda n:n.height == 0):
                    name = node.name
                    folder_id = node.id
                    parent_folder_id = node.parent_id
                    mime_type = node.mime_type
                    logger.debug('%s,%s,%s,%s', name, folder_id, mime_type, parent_folder_id)
                    #logger.debug(node) # name = node.tag, folder_id = node.identifier
                    #r = LogicGdrive.get_file_info(folder_id)
                    #logger.debug('%s,%s,%s,%s', r['id'],r['name'],r['mimeType'],r['parent'])

                    entity = None
                    entity = ModelGdriveItem.get_by_folder_id(folder_id)
                    if entity != None:
                        logger.debug(u'SKIP: 이미 존재하는 아이템: %s', name)
                        rcount += 1
                        continue

                    #info = LogicGdrive.search_metadata(rule.agent_type, name)
                    if rule.agent_type == 'ktv':
                        r = LogicGdrive.search_ktv(name)
                        if r == None:
                            logger.debug(u'메타정보 조회실패: %s:%s', rule.agent_type, name)
                            continue
                    else: 
                        r = LogicGdrive.search_metadata(rule.agent_type, name)
                        if len(r) == 0:
                            logger.debug(u'메타정보 조회실패: %s:%s', rule.agent_type, name)
                            continue

                    info = LogicGdrive.info_metadata(rule.agent_type, r['code'], r['title'])
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

                    if rule.agent_type.startswith('av'):
                        entity = LogicAv.create_av_entity(info)
                    else:
                        entity = LogicGdrive.create_gd_entity(info)
                    count += 1

                rule.item_count += count
                rule.save()
                data = {'type':'success', 'msg':u'경로규칙 <strong>"{n}"</strong>에 {c} 항목을 추가하였습니다.(중복:{r})'.format(n=rule.name, c=count, r=rcount)}
                socketio.emit("notify", data, namespace='/framework', broadcate=True)
                LogicGdrive.RuleJobQueue.task_done()
                logger.debug('rule_handler_thread: ended(name:%s, new: %d, skip: %d)', rule.name, count, rcount)
                time.sleep(1)

            except Exception as e:
                logger.debug('Exception:%s', e)
                logger.debug(traceback.format_exc())

    @staticmethod
    def register_rule(req):
        try:
            info = {}
            info['name'] = py_urllib.unquote(req.form['rule_name'])
            info['agent_type'] = py_urllib.unquote(req.form['agent_type'])
            info['root_folder_id'] = py_urllib.unquote(req.form['root_folder_id'])
            info['root_full_path'] = py_urllib.unquote(req.form['root_full_path'])
            info['max_depth'] = req.form['max_depth']
            info['target_folder_id'] = py_urllib.unquote(req.form['target_folder_id'])
            info['target_full_path'] = py_urllib.unquote(req.form['target_full_path'])
            info['use_subfolder'] = True if req.form['use_subfolder'] == 'True' else False
            info['subfolder_rule'] = py_urllib.unquote(req.form['subfolder_rule'])
            info['use_plex'] = True if req.form['use_plex'] == 'True' else False
            info['use_schedule'] = True if req.form['use_schedule'] == 'True' else False

            entity = ModelRuleItem(info)
            entity.save()
            return {'ret':'success', 'msg':u'등록을 완료하였습니다.'}
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def modify_rule(req):
        try:
            id = int(req.form['id'])
            entity = ModelRuleItem.get_by_id(id)
            entity.name = py_urllib.unquote(req.form['curr_rule_name'])
            entity.agent_type = py_urllib.unquote(req.form['curr_agent_type'])
            entity.root_folder_id = py_urllib.unquote(req.form['curr_root_folder_id'])
            entity.root_full_path = py_urllib.unquote(req.form['curr_root_full_path'])
            entity.max_depth = req.form['curr_max_depth']
            entity.target_folder_id = py_urllib.unquote(req.form['curr_target_folder_id'])
            entity.target_full_path = py_urllib.unquote(req.form['curr_target_full_path'])
            entity.use_subfolder = True if req.form['curr_use_subfolder'] == 'True' else False
            entity.subfolder_rule = py_urllib.unquote(req.form['curr_subfolder_rule'])
            entity.use_plex = True if req.form['curr_use_plex'] == 'True' else False
            entity.use_schedule = True if req.form['curr_use_schedule'] == 'True' else False
            entity.save()
            return {'ret':'success', 'msg':u'{n} 항목이 수정 되었습니다.'.format(n=entity.name)} 
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def create_gd_entity(info):
        try:
            entity = ModelGdriveItem(info['name'], info['folder_id'], info['rule_name'], info['rule_id'])
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
    def change_text_for_use_filename(text):
        try:
            import re
            return re.sub('[\\/:*?\"<>|\[\]]', '', text).strip()
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_shortcut_name(entity):
        try:
            rule_map = {
                    'ktv'  : ['year' ,'genre','studio'],
                    'ftv'  : ['year' ,'genre','studio'],
                    'movie': ['year' ,'genre','country'],
                    'avdvd': ['code' ,'year' ,'genre','studio'],
                    'avama': ['code' ,'year' ,'genre','studio'],
                    }

            key = '{}_shortcut_name_rule'.format(entity.agent_type)
            title = LogicGdrive.change_text_for_use_filename(entity.title)
            name = ModelSetting.get(key)
            name = name.replace('{title}', title)
            dict_entity = entity.as_dict()
            for keyword in rule_map[entity.agent_type]:
                if name.find('{'+keyword+'}') != -1:
                    name = name.replace('{'+keyword+'}', py_unicode(str(dict_entity[keyword])))

            return name

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def create_shortcut(db_id):
        global service
        try:
            #if service == None: LogicGdrive.initialize()
            entity = ModelGdriveItem.get_by_id(db_id)
            shortcut_name = LogicGdrive.get_shortcut_name(entity)
            logger.debug('create_shortcut: title(%s), shortcut(%s)', entity.title, shortcut_name)

            shortcut_metadata = {
                'name': shortcut_name,
                'mimeType': 'application/vnd.google-apps.shortcut',
                'shortcutDetails': {
                    'targetId': entity.folder_id
                },
                'parents': [entity.target_folder_id]
            }
            shortcut = service.files().create(body=shortcut_metadata, 
                    fields='id,shortcutDetails').execute()
            #logger.debug(json.dumps(shortcut, indent=2))

            # entity update
            entity.shortcut_created = True
            entity.shortcut_folder_id = py_unicode(shortcut['id'])
            entity.gdrive_path = LogicGdrive.get_gdrive_full_path(entity.shortcut_folder_id)
            entity.plex_path = LogicGdrive.get_plex_path(entity.gdrive_path)
            logger.debug('gdpath(%s),plexpath(%s)', entity.gdrive_path, entity.plex_path)
            entity.save()

            rule = ModelRuleItem.get_by_id(entity.rule_id)
            rule.shortcut_count += 1
            rule.save()

            logger.debug(u'바로가기 생성완료(%s)', entity.shortcut_folder_id)
            ret = { 'ret':'success', 'msg':'바로가기 생성 성공{n}'.format(n=entity.name) }

            if rule.use_plex:
                LogicGdrive.PlexScannerQueue.put({'id':entity.id, 'now':datetime.now()})
                ret = { 'ret':'success', 'msg':'바로가기 생성 성공{n}, 스캔명령 전송대기'.format(n=entity.name) }
            return ret

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'생성실패! 로그를 확인해주세요.' }

    @staticmethod
    def apply_meta(req):
        try:
            db_id = int(req.form['id'])
            entity = ModelGdriveItem.get_by_id(db_id)

            code = req.form['code']
            title = req.form['title']
            site = req.form['site']

            info = LogicGdrive.info_metadata(entity.agent_type, code, title)
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
        global service
        try:
            #if service == None: LogicGdrive.initialize()
            entity = ModelGdriveItem.get_by_id(db_id)
            info = LogicGdrive.info_metadata(entity.agent_type, entity.code, entity.title)
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

    @staticmethod
    def get_category_rules():
        try:
            rules = {}
            lists = ModelSetting.get_list('gdrive_category_rules', '\n')
            lists = Util.get_list_except_empty(lists)
            for line in lists:
                agent_type, category, gdriveid, plexid = line.split(',')
                logger.debug('category_rule: %s,%s,%s,%s', agent_type, category, gdriveid, plexid)
                rules[category] = [agent_type.lower(), gdriveid, plexid]

            return rules
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_rule_names():
        try:
            rule_entities = ModelRuleItem.get_all_entities_except_av()
            rule_names = list(set([x.name for x in rule_entities]))
            return rule_names
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_agent_types():
        try:
            rule_entities = ModelRuleItem.get_all_entities_except_av()
            agent_types = list(set([x.agent_type for x in rule_entities]))
            return agent_types
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def search_ktv_ott(title):
        try:
            info = {}
            site_list = ['tving', 'wavve']
            from metadata.logic_ott_show import LogicOttShow
            LogicOttShow = LogicOttShow(LogicOttShow)

            r = LogicOttShow.search(title)
            if len(r) == 0: return None

            code = None
            for site in site_list: 
                if site in r: code = r[site][0]['code']; break;
            if not code: return None

            r = LogicOttShow.info(code)
            if not r: return None

            info['code'] = r['code']
            info['title'] = r['title']
            info['site'] = site
            info['status'] = r['status']
            score = 0
            for p in r['thumb']:
                if p['score'] > score and p['aspect'] == 'poster':
                    score = p['score']
                    info['poster_url'] = p['value']
                    if score == 100: break
            info['genre'] = r['genre'][0] if len(r['genre']) > 0 else u'기타'
            info['studio'] = r['studio'] if 'studio' in info else u''
            info['year'] = r['year'] if 'year' in r else 1900
            return info

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def search_ktv(name, year=None):
        try:
            from lib_metadata import SiteDaumTv
            ktv_info = {}

            title, year = LogicGdrive.get_title_year_from_dname(name)
            logger.debug('search_ktv: title(%s), year(%s)', title, year if year != None else '-')

            #if year != None: search_word = '{}|{}'.format(title, str(year))
            #else: search_word = title
            search_word = title

            return LogicGdrive.search_metadata('ktv', search_word)

            """
            ret = SiteDaumTv.search(title, year=year)
            if ret['ret'] != 'success':
                logger.error('failed to get daum info(%s), try to get ott info', title)
                info = LogicGdrive.search_ktv_ott(title)
                if info is None:
                    logger.error('failed to get ott show info(%s)', title)
                    return None
                return info
            info = ret['data']
            #logger.debug(json.dumps(info, indent=2))
            logger.debug('#TEST: code:%s, title:%s', info['code'], info['title'])

            ktv_info['title'] = info['title']
            ktv_info['code'] = info['code'] if 'code' in info else u''
            # 1: 방송중, 2: 종영, 0: 방송예정
            ktv_info['status'] = info['status'] if 'status' in info else -1
            ktv_info['poster_url'] = info['image_url'] if 'image_url' in info else u''
            ktv_info['genre'] = info['genre'] if 'genre' in info else u''
            ktv_info['site'] = 'daum'
            ktv_info['studio'] = info['studio'] if 'studio' in info else u''
            ktv_info['year'] = int(info['year']) if 'year' in info else 1900
            return ktv_info
            """

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def get_ktv_meta_list(metadata):
        meta_list = []
        for site in metadata:
            if site == 'daum': 
                m = metadata[site]
                info = {}
                info['site'] = site
                info['code'] = m['code']
                info['title'] = m['title']
                info['genre'] = m['genre']
                info['studio'] = m['studio']
                info['score'] = m['score']
                info['poster_url'] = m['image_url']
                meta_list.append(info)
            else:
                count = 0
                for m in metadata[site]:
                    if ModelSetting.get_int('ktv_meta_result_limit_per_site') == count: break
                    info = {}
                    info['site'] = site
                    info['code'] = m['code']
                    info['title'] = m['title']
                    info['genre'] = m['genre']
                    info['studio'] = m['studio']
                    info['score'] = m['score']
                    info['poster_url'] = m['image_url']
                    count += 1
                    meta_list.append(info)

        return meta_list

    @staticmethod
    def get_movie_meta_list(metadata):
        meta_list = []
        count = 0
        for m in metadata:
            info = {}
            info['site'] = m['site']
            info['code'] = m['code']
            info['title'] = m['title']
            info['year'] = m['year']
            info['studio'] = u''
            info['score'] = m['score']
            info['poster_url'] = m['image_url']
            meta_list.append(info)
        return meta_list

    @staticmethod
    def search_metadata(agent_type, title, get_list=False):
        from metadata.logic_ktv import LogicKtv
        from metadata.logic_movie import LogicMovie
        from metadata.logic_ftv import LogicFtv
        from metadata.logic_jav_censored import LogicJavCensored
        from metadata.logic_jav_censored_ama import LogicJavCensoredAma

        agent_map = {'ktv':LogicKtv(LogicKtv), 'ftv':LogicFtv(LogicFtv), 
                'movie':LogicMovie(LogicMovie),
                'avdvd':LogicJavCensored(LogicJavCensored), 'avama':LogicJavCensoredAma(LogicJavCensoredAma)}

        site_map = {'ktv':['daum','tving','wavve'],
                'ftv':['daum', 'tvdb', 'tmdb', 'watcha', 'tmdb'],
                'movie':['naver', 'daum', 'tmdb', 'watcha', 'wavve', 'tving'],
                'avdvd':['dmm', 'javbus'],
                'avama':['mgstage', 'jav321', 'r18']}

        logger.debug('agent_type: %s, title:%s', agent_type, title)
        #TV
        if agent_type == 'ktv':
            metadata = agent_map[agent_type].search(title, manual=True)
        elif agent_type == 'movie':
            title, year = LogicGdrive.get_title_year_from_dname(title)
            metadata = agent_map[agent_type].search(title, year, manual=True)
        elif agent_type == 'avdvd':
            metadata = agent_map[agent_type].search(title, all_find=True, do_trans=True)
            #logger.debug(json.dumps(metadata, indent=2))

        if get_list:
            if agent_type == 'ktv': meta_list = LogicGdrive.get_ktv_meta_list(metadata)
            else: meta_list = LogicGdrive.get_movie_meta_list(metadata)
            return {'ret':'success', 'data':meta_list}

        info = {}
        for site in site_map[agent_type]:
            if agent_type == 'ktv': # TV
                if site in metadata:
                    if site != 'daum': r = metadata[site][0]
                    else: r = metadata[site]
                    logger.debug('TEST: code:%s, title:%s', r['code'], r['title'])
                    info['code'] = r['code']
                    info['status'] = r['status'] if 'status' in r else 2
                    info['title'] = r['title']
                    info['site'] = r['site']
                    info['poster_url'] = r['image_url']
                    info['studio'] = r['studio']
                    info['year'] = r['year'] if 'year' in r else 1900
                    info['genre'] = r['genre'] if 'genre' in r else ''
                    break
            elif agent_type == 'movie':
                for r in metadata:
                    info['code'] = r['code']
                    info['status'] = 2
                    info['title'] = r['title']
                    info['site'] = r['site']
                    info['poster_url'] = r['image_url']
                    info['studio'] = u''
                    info['year'] = r['year']
                    info['genre'] = r['genre'] if 'genre' in r else ''
                    break
            else: # av
                for r in metadata:
                    info['code'] = r['code']
                    info['ui_code'] = r['ui_code']
                    info['status'] = 2
                    info['title'] = r['title_ko'] if r['title_ko'] != '' else r['title']
                    info['site'] = r['site']
                    info['poster_url'] = r['image_url']
                    info['studio'] = u''
                    info['year'] = r['year']
                    info['genre'] = r['genre'] if 'genre' in r else ''
                    break

        return info
    
    
    @staticmethod
    def get_additional_prefix_by_code(code):
        entity = ModelGdriveItem.get_by_code(code)
        rule = ModelRuleItem.get_by_id(entity.rule_id)
        return rule.additional_prefix

    @staticmethod
    def info_metadata(agent_type, code, title):
        from metadata.logic_ktv import LogicKtv
        from metadata.logic_movie import LogicMovie
        from metadata.logic_ftv import LogicFtv
        from metadata.logic_jav_censored import LogicJavCensored
        from metadata.logic_jav_censored_ama import LogicJavCensoredAma

        agent_map = {'ktv':LogicKtv(LogicKtv), 'ftv':LogicFtv(LogicFtv), 
                'movie':LogicMovie(LogicMovie),
                'avdvd':LogicJavCensored(LogicJavCensored), 'avama':LogicJavCensoredAma(LogicJavCensoredAma)}

        site_map = {'ktv':['daum','tving','wavve'],
                'ftv':['daum', 'tvdb', 'tmdb', 'watcha', 'tmdb'],
                'movie':['naver', 'daum', 'tmdb', 'watcha', 'wavve', 'tving'],
                'avdvd':['dmm', 'javbus'],
                'avama':['mgstage', 'jav321', 'r18']}

        #TV
        logger.debug('agent_type:%s, code:%s, title:%s', agent_type, code, title)
        title, year = LogicGdrive.get_title_year_from_dname(title)
        if agent_type == 'ktv':
            metadata = agent_map[agent_type].info(code, title)
            if metadata == None:
                prefix = LogicGdrive.get_additional_prefix_by_code(code)
                if prefix == u'': return None
                tmp = prefix + ' ' + title
                logger.debug('meta info failed add prefix(%s)', tmp)
                metadata = agent_map[agent_type].info(code, tmp)
        else:
            metadata = agent_map[agent_type].info(code)


        #debug
        logger.debug(json.dumps(metadata, indent=2))
        info = {}
        thumb = None
        if agent_type.startswith('av'):
            metadata['ui_code'] = code
            return LogicAv.meta_info_map(metadata)
        elif agent_type == 'ktv':
            if 'thumb' in metadata:
                thumbs = sorted(metadata['thumb'], key=lambda x:x['score'], reverse=True)
                for th in thumbs:
                    if th['aspect'] == 'poster':
                        thumb = th
                        break
                if thumb == None:
                    thumb = thumbs[0]
        elif agent_type == 'movie':
            for art in metadata['art']:
                if art['aspect'] == 'poster':
                    thumb = art
                    break


        info['code'] = metadata['code']
        info['status'] = metadata['status'] if 'status' in metadata else 2
        info['title'] = metadata['title']
        info['site'] = metadata['site']
        info['poster_url'] = thumb['value'] if thumb['thumb'] == "" else thumb['thumb']
        info['studio'] = metadata['studio']
        info['year'] = metadata['year'] if 'year' in metadata else 1900
        info['genre'] = metadata['genre'][0] if 'genre' in metadata else u''
        if len(metadata['country']) > 0: info['country'] = metadata['country'][0]
        else: info['country'] = u'한국' if agent_type == 'ktv' else u''
        return info
    
    @staticmethod
    def get_all_jsonfiles(target_path):
        file_list = []

        for (path, dir, files) in os.walk(target_path):
            for filename in files:
                ext = os.path.splitext(filename)[-1]
                if ext == '.json':
                    file_list.append(os.path.join(path, filename))

        return file_list

    @staticmethod
    def get_plex_path(gdrive_path):
        try:
            rules = ModelSetting.get('gdrive_plex_path_rule')
            if rules == u'' or rules.find('|') == -1:
                return gdrive_path
            if rules is not None:
                rules = rules.split(',')
                rules = sorted(rules, key=lambda x:len(x.split('|')[0]), reverse=True)
                for rule in rules:
                    tmp = rule.split('|')

                    if gdrive_path.startswith(tmp[0]):
                        ret = gdrive_path.replace(tmp[0], tmp[1])
                        # SJVA-PMS의 플랫폼이 다른 경우
                        if tmp[0][0] != tmp[1][0]:
                            if gdrive_path[0] == '/': # Linux   -> Windows
                                ret = ret.replace('/', '\\')
                            else:                  # Windows -> Linux
                                ret = ret.replace('\\', '/')
                        return ret
            return gdrive_path

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_file_info(folder_id):
        global service
        info = service.files().get(fileId=folder_id, fields='id, name, mimeType, parents').execute()
        ret = {'id':info['id'], 'mimeType':info['mimeType'], 'name':info['name'], 'parent':info['parents'][0]}
        return ret

    @staticmethod
    def get_gdrive_full_path(folder_id):
        global service
        #if service is None: LogicGdrive.initialize()
        pathes = []
        parent_id = folder_id
        while True:
            r = service.files().get(fileId=parent_id, fields='id, name, mimeType, parents').execute()
            if 'parents' in r:
                #logger.debug('{}:{}/{}'.format(r['name'], r['parents'][0], parent_id))
                parent_id = r['parents'][0]
                pathes.append(r['name'])
            else:
                #logger.debug('{}:{}'.format(r['name'], parent_id))
                pathes.append(r['name'])
                break

        pathes.append('')
        pathes.reverse()
        return u'/'.join(pathes)

    @staticmethod
    def get_all_folders_in_folder(root_folder_id, last_searched_time):
        global service

        child_folders = {}
        page_token = None
        time_str = ModelSetting.get('gdrive_last_search_time')
        if last_searched_time == None:
            query = "mimeType='application/vnd.google-apps.folder' \
                    and '{r}' in parents".format(r=root_folder_id)
        else:
            time_str = last_searched_time.strftime('%Y-%m-%dT%H:%M:%S+09:00')
            query = "mimeType='application/vnd.google-apps.folder' \
                    and '{r}' in parents and modifiedTime>'{t}'".format(r=root_folder_id, t=time_str)

        while True:
            response = service.files().list(q=query,
                    spaces='drive',
                    pageSize=1000,
                    fields='nextPageToken, files(id, name, parents, modifiedTime)',
                    pageToken=page_token).execute()
    
            folders = response.get('files', [])
            page_token = response.get('nextPageToken', None)

            for folder in folders:
                child_folders[folder['id']] = folder['parents'][0]
            if page_token is None: break
    
        return child_folders

    @staticmethod
    def get_subfolders_of_folder(folder_to_search, all_folders):
        temp_list = [k for k, v in all_folders.items() if v == folder_to_search]
        for sub_folder in temp_list:
            yield sub_folder
            for x in LogicGdrive.get_subfolders_of_folder(sub_folder, all_folders):
                yield x

    @staticmethod
    def get_all_folders(root_folder_id, last_searched_time):
        all_folders = LogicGdrive.get_all_folders_in_folder(root_folder_id, last_searched_time)
        target_folder_list = []
        for folder in LogicGdrive.get_subfolders_of_folder(root_folder_id, all_folders):
            target_folder_list.append(folder)
        return target_folder_list

    ############### NEW STYLE 

    @staticmethod
    def get_children(target_folder_id):
        global service
        children = []
        try:
            page_token = None
            query = "mimeType='application/vnd.google-apps.folder'\
                    and '{}' in parents".format(target_folder_id)

            while True:
                try:
                    r = service.files().list(q=query, 
                            spaces='drive',
                            pageSize=1000,
                            fields='nextPageToken, files(id, name, parents, mimeType)',
                            pageToken=page_token).execute()
                
                    page_token = r.get('nextPageToken', None)
                    for child in r.get('files', []): children.append(child)
                    if page_token is None: break
                except:
                    service = LogicGdrive.switch_service_account()
                    if service == None:
                        return None

            return children

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def populate_tree(parent, parent_id, depth):
        global service
        try:
            children = LogicGdrive.get_children(parent_id)
            children_nodes = []
            if len(children) > 0:
                for child in children:
                    node = Node(child['name'], parent=parent, id=child['id'], parent_id=parent_id, mime_type=child['mimeType'])
                    children_nodes.append(node)
                    logger.debug('add-tree:{},{},{}'.format(node.name, node.parent_id, node.id))

            if depth-1 == 0: return
            for node in children_nodes:
                LogicGdrive.populate_tree(node, node.id, depth-1)

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_all_subfolders(root_folder_id, name=None, max_depth=1):
        try:
            if name == None: name = LogicGdrive.get_file_info(root_folder_id)['name']
            root = Node(name, id=root_folder_id)
            logger.debug('start1')
            LogicGdrive.populate_tree(root, root_folder_id, max_depth)
            logger.debug('end1')
            return root
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_files(target_path, target_ext_list=None, except_name_list=None):
        file_list = []

        for (path, dir, files) in os.walk(target_path):
            for filename in files:
                ext = os.path.splitext(filename)[-1]
                if target_ext_list != None:
                    if ext not in target_ext_list:
                        continue

                if except_name_list != None:
                    for except_name in except_name_list:
                        if path.find(except_name) != -1:
                            continue

                file_list.append(os.path.join(path, filename))

        return file_list

    @staticmethod
    def get_title_year_from_dname(name):
        try:
            rx = r"\((?P<year>\d{4})?\)"
            match = re.compile(rx).search(name)
            if match: year = int(match.group('year'))
            else: year = None

            #title = re.sub('(\[(\w+|.+)\])', '', name)
            title = re.sub('(\[(\w+|.+)\])|\(\d{4}\)','',name)
            return title.strip(), year
            
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

                req = LogicGdrive.PlexScannerQueue.get()
                now = datetime.now()
                logger.debug('plex_scanner_thread...job-started()')

                item_id  = req['id']
                queued_time= req['now']

                entity = ModelGdriveItem.get_by_id(item_id)
                plex_path = os.path.dirname(entity.plex_path)
                section_id = plex.LogicNormal.get_section_id_by_filepath(plex_path)
                if section_id == -1:
                    logger.error('failed to get section_id by path(%s)', plex_path)
                    data = {'type':'warning', 'msg':'Plex경로오류! \"{p}\" 경로를 확인해 주세요'.format(p=entity.plex_path)}
                    socketio.emit("notify", data, namespace='/framework', broadcate=True)
                    LogicGdrive.PlexScannerQueue.task_done()
                    continue

                timediff = queued_time + timedelta(seconds=scan_delay) - now
                delay = int(timediff.total_seconds())
                if delay < 0: delay = 0
                if delay < scan_min_limit and prev_section_id == section_id: 
                    logger.debug('스캔명령 전송 스킵...(%d)s', delay)
                    LogicGdrive.PlexScannerQueue.task_done()
                    continue

                logger.debug('스캔명령 전송 대기...(%d)s', delay)
                time.sleep(delay)

                logger.debug('스캔명령 전송: server(%s), token(%s), section_id(%s)', server, token, section_id)
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
                LogicGdrive.PlexScannerQueue.task_done()
                logger.debug('plex_scanner_thread...job-end()')
            except Exception as e:
                logger.debug('Exception:%s', e)
                logger.debug(traceback.format_exc())


class ModelGdriveItem(db.Model):
    __tablename__ = '%s_gdrive_item' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    reserved = db.Column(db.JSON)

    # basic info
    rule_name = db.Column(db.String)   # from category_rules
    rule_id = db.Column(db.Integer)
    agent_type = db.Column(db.String) # ktv, ftv, movie, av?
    root_folder_id = db.Column(db.String)
    target_folder_id = db.Column(db.String)

    shortcut_created = db.Column(db.Boolean)
    shortcut_folder_id = db.Column(db.String)
    gdrive_path = db.Column(db.String)
    plex_path = db.Column(db.String)

    # info from gdrive
    name = db.Column(db.String)
    mime_type = db.Column(db.String)
    folder_id = db.Column(db.String)
    parent_folder_id = db.Column(db.String)

    # info from metadata
    code = db.Column(db.String)
    status = db.Column(db.Integer)
    title = db.Column(db.String)
    genre = db.Column(db.String)
    site = db.Column(db.String)
    studio = db.Column(db.String)
    country = db.Column(db.String)
    poster_url = db.Column(db.String)
    year = db.Column(db.Integer)

    def __init__(self, name, folder_id, rule_name, rule_id):
        self.created_time = datetime.now()
        self.name = py_unicode(name)
        self.folder_id = py_unicode(folder_id)
        self.rule_name = py_unicode(rule_name)
        self.rule_id = rule_id
        self.shortcut_created = False

    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        ret = {x.name: getattr(self, x.name) for x in self.__table__.columns}
        ret['created_time'] = self.created_time.strftime('%m-%d %H:%M:%S') 
        return ret
    
    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, id):
        return db.session.query(cls).filter_by(id=id).first()
    
    @classmethod
    def get_by_folder_id(cls, folder_id):
        return db.session.query(cls).filter_by(folder_id=folder_id).first()

    @classmethod
    def get_by_code(cls, code):
        return db.session.query(cls).filter_by(code=code).first()

    @classmethod
    def get_shortcut_created_entities(cls):
        return db.session.query(cls).filter_by(shortcut_created=shortcut_created).first()

    @classmethod
    def web_list(cls, req):
        try:
            ret = {}
            page = 1
            page_size = 30
            job_id = ''
            search = ''
            category = ''
            if 'page' in req.form:
                page = int(req.form['page'])
            if 'search_word' in req.form:
                search = req.form['search_word']
            rule_name = req.form['category'] if 'category' in req.form else 'all'
            shortcut_status = req.form['shortcut_status'] if 'shortcut_status' in req.form else 'all'
            #option = req.form['option']
            #order = req.form['order'] if 'order' in req.form else 'desc'

            #query = cls.make_query(search=search, option=option, order=order)
            query = cls.make_query(search=search, rule_name=rule_name, shortcut_status=shortcut_status)
            count = query.count()
            query = query.limit(page_size).offset((page-1)*page_size)
            logger.debug('cls count:%s', count)
            lists = query.all()
            ret['list'] = [item.as_dict() for item in lists]
            ret['paging'] = Util.get_paging_info(count, page, page_size)
            #ModelSetting.set('jav_censored_last_list_option', '%s|%s|%s|%s' % (option, order, search, page))
            return ret
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @classmethod
    def make_query(cls, search='', rule_name='all', shortcut_status='all', order='desc'):
        query = db.session.query(cls)
        if search is not None and search != '':
            if search.find('|') != -1:
                tmp = search.split('|')
                conditions = []
                for tt in tmp:
                    if tt != '':
                        conditions.append(cls.title.like('%'+tt.strip()+'%') )
                query = query.filter(or_(*conditions))
            elif search.find(',') != -1:
                tmp = search.split(',')
                for tt in tmp:
                    if tt != '':
                        query = query.filter(cls.title.like('%'+tt.strip()+'%'))
            else:
                query = query.filter(or_(cls.title.like('%'+search+'%'), cls.name.like('%'+search+'%')))

        if rule_name != 'all':
            query = query.filter(cls.rule_name == rule_name)

        if shortcut_status != 'all':
            if shortcut_status == 'true': query = query.filter(cls.shortcut_created == True)
            else: query = query.filter(cls.shortcut_created == False)

        if order == 'desc':
            query = query.order_by(desc(cls.id))
        else:
            query = query.order_by(cls.id)

        return query 



class ModelRuleItem(db.Model):
    __tablename__ = '%s_rule_item' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    reserved = db.Column(db.JSON)

    name = db.Column(db.String)
    agent_type = db.Column(db.String)
    root_folder_id = db.Column(db.String)
    root_full_path = db.Column(db.String)
    max_depth = db.Column(db.Integer)
    target_folder_id = db.Column(db.String)
    target_full_path = db.Column(db.String)
    item_count = db.Column(db.Integer)
    shortcut_count = db.Column(db.Integer)
    use_subfolder = db.Column(db.Boolean)
    subfolder_rule = db.Column(db.String)

    last_searched_time = db.Column(db.DateTime)
    use_schedule = db.Column(db.Boolean)
    use_plex = db.Column(db.Boolean)

    def __init__(self, info):
        self.created_time = datetime.now()

        self.name = py_unicode(info['name'])
        self.agent_type = py_unicode(info['agent_type'])
        self.root_folder_id = py_unicode(info['root_folder_id'])
        self.root_full_path = py_unicode(info['root_full_path'])
        self.max_depth = info['max_depth']
        self.target_folder_id = py_unicode(info['target_folder_id'])
        self.target_full_path = py_unicode(info['target_full_path'])
        self.item_count = 0
        self.shortcut_count = 0

        self.use_sub_folder = info['use_subfolder']
        self.subfolder_rule = py_unicode(info['subfolder_rule'])
        self.use_schedule = info['use_schedule']
        self.use_plex = info['use_plex']
        self.last_search_time = None

    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        ret = {x.name: getattr(self, x.name) for x in self.__table__.columns}
        ret['created_time'] = self.created_time.strftime('%m-%d %H:%M:%S') 
        if self.last_searched_time == None:
            ret['last_searched_time'] = u'-'
        else:
            ret['last_searched_time'] = self.last_searched_time.strftime('%m-%d %H:%M:%S') 
        return ret

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, id):
        return db.session.query(cls).filter_by(id=id).first()
    
    @classmethod
    def get_by_name(cls, name):
        return db.session.query(cls).filter_by(name=name).first()

    @classmethod
    def get_scheduled_entities(cls):
        return db.session.query(cls).filter_by(use_schedule=True).all()
    
    @classmethod
    def get_by_root_folder_id(cls, folder_id):
        return db.session.query(cls).filter_by(root_folder_id=folder_id).first()

    @classmethod
    def get_by_target_folder_id(cls, folder_id):
        return db.session.query(cls).filter_by(target_folder_id=folder_id).first()

    @classmethod
    def get_all_entities(cls):
        return db.session.query(cls).all()

    @classmethod
    def get_all_entities_except_av(cls):
        query = db.session.query(cls)
        return query.filter(not_(cls.agent_type.like('av%'))).all()

    @classmethod
    def get_all_av_entities(cls):
        query = db.session.query(cls)
        return query.filter(cls.agent_type.like('av%')).all()

    @classmethod
    def web_list(cls, req):
        try:
            ret = {}
            page = 1
            page_size = 30
            job_id = ''
            search = ''
            category = ''
            if 'page' in req.form:
                page = int(req.form['page'])
            if 'search_word' in req.form:
                search = req.form['search_word']
            agent_type = req.form['agent_type'] if 'agent_type' in req.form else 'all'

            query = cls.make_query(search=search, agent_type=agent_type)
            count = query.count()
            query = query.limit(page_size).offset((page-1)*page_size)
            logger.debug('cls count:%s', count)
            lists = query.all()
            ret['list'] = [item.as_dict() for item in lists]
            ret['paging'] = Util.get_paging_info(count, page, page_size)
            return ret
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @classmethod
    def make_query(cls, search='', agent_type='all', order='desc'):
        query = db.session.query(cls)
        if search is not None and search != '':
            if search.find('|') != -1:
                tmp = search.split('|')
                conditions = []
                for tt in tmp:
                    if tt != '':
                        conditions.append(cls.title.like('%'+tt.strip()+'%') )
                query = query.filter(or_(*conditions))
            elif search.find(',') != -1:
                tmp = search.split(',')
                for tt in tmp:
                    if tt != '':
                        query = query.filter(cls.title.like('%'+tt.strip()+'%'))
            else:
                query = query.filter(or_(cls.title.like('%'+search+'%'), cls.name.like('%'+search+'%')))

        if agent_type != 'all':
            query = query.filter(cls.agent_type == agent_type)
        if order == 'desc':
            query = query.order_by(desc(cls.id))
        else:
            query = query.order_by(cls.id)

        return query 



