# -*- coding: utf-8 -*-
#########################################################
# python
import os, sys, traceback, re, json, threading, time, shutil
from datetime import datetime, timedelta
# third-party
import requests
# third-party
from flask import request, render_template, jsonify, redirect, Response
from sqlalchemy import or_, and_, func, not_, desc
import random

# sjva 공용
from framework import db, scheduler, path_data, socketio, SystemModelSetting, app, celery, py_unicode, py_urllib, py_queue
from framework.util import Util
from framework.common.util import headers, get_json_with_auth_session
from framework.common.plugin import LogicModuleBase, default_route_socketio
from tool_expand import ToolExpandFileProcess
from tool_base import ToolBaseNotify

# GDrive Lib
from lib_gdrive import LibGdrive
from .models import ModelRuleItem, ModelTvMvItem, ModelAvItem, ModelSubFolderItem, ModelSubItem

# 패키지
from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

#########################################################

class ScmUtil(LogicModuleBase):
    # 경로규칙 관련
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
            info['use_auto_create_shortcut'] = True if req.form['use_auto_create_shortcut'] == 'True' else False

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
            rule = ModelRuleItem.get_by_id(id)
            col_values = {}

            if rule.name != py_urllib.unquote(req.form['curr_rule_name']):
                rule.name = py_urllib.unquote(req.form['curr_rule_name'])
                col_values['rule_name'] = rule.name
            if rule.agent_type != py_urllib.unquote(req.form['curr_agent_type']):
                rule.agent_type = py_urllib.unquote(req.form['curr_agent_type'])
                col_values['agent_type'] = rule.agent_type
            if rule.root_folder_id != py_urllib.unquote(req.form['curr_root_folder_id']):
                rule.root_folder_id = py_urllib.unquote(req.form['curr_root_folder_id'])
                col_values['root_folder_id'] = rule.root_folder_id
            if rule.target_folder_id != py_urllib.unquote(req.form['curr_target_folder_id']):
                rule.target_folder_id = py_urllib.unquote(req.form['curr_target_folder_id'])
                col_values['target_folder_id'] = rule.target_folder_id

            rule.root_full_path = py_urllib.unquote(req.form['curr_root_full_path'])
            rule.max_depth = req.form['curr_max_depth']
            rule.target_full_path = py_urllib.unquote(req.form['curr_target_full_path'])
            rule.use_subfolder = True if req.form['curr_use_subfolder'] == 'True' else False
            rule.subfolder_rule = py_urllib.unquote(req.form['curr_subfolder_rule'])
            rule.use_plex = True if req.form['curr_use_plex'] == 'True' else False
            rule.use_schedule = True if req.form['curr_use_schedule'] == 'True' else False
            rule.use_auto_create_shortcut = True if req.form['curr_use_auto_create_shortcut'] == 'True' else False
            rule.save()

            # rule 에 해당하는 item 들의 정보갱신
            if len(col_values) > 0:
                if rule.agent_type.startswith('av'):
                    ModelAvItem.update_all_rows_by_rule_id(rule.id, col_values)
                else:
                    ModelTvMvItem.update_all_rows_by_rule_id(rule.id, col_values)

            return {'ret':'success', 'msg':u'{n} 항목이 수정 되었습니다.'.format(n=rule.name)} 
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def update_rule_count(req):
        try:
            id = int(req.form['id'])
            rule = ModelRuleItem.get_by_id(id)
            if rule.agent_type.startswith('av'):
                rule.item_count = ModelAvItem.get_item_count(rule.id)
                rule.shortcut_count = ModelAvItem.get_shortcut_count(rule.id)
            else:
                rule.item_count = ModelTvMvItem.get_item_count(rule.id)
                rule.shortcut_count = ModelTvMvItem.get_shortcut_count(rule.id)
            rule.save()
            return {'ret':'success', 'msg':u'항목건수 동기화 완료: item({}),shortcut({})'.format(rule.item_count, rule.shortcut_count)} 
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def create_tvmv_entity(info):
        try:
            entity = None
            entity = ModelTvMvItem(info['name'], info['folder_id'], info['rule_name'], info['rule_id'])
            #entity = ModelTvMvItem.get_by_folder_id(info['folder_id'])
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
            entity.orig_gdrive_path = py_unicode(info['orig_gdrive_path'])
            entity.save()
            return entity
        
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def create_av_entity(info):
        try:
            entity = None
            entity = ModelAvItem(info['ui_code'], info['folder_id'])
            #entity = ModelAvItem.get_by_folder_id(info['folder_id'])
            if entity == None: return None
            entity.rule_name = py_unicode(info['rule_name'])
            entity.rule_id = info['rule_id']
            entity.agent_type = py_unicode(info['agent_type'])
            entity.root_folder_id = py_unicode(info['root_folder_id'])
            entity.target_folder_id = py_unicode(info['target_folder_id'])
            entity.name = py_unicode(info['name'])
            entity.mime_type = py_unicode(info['mime_type'])
            entity.parent_folder_id = py_unicode(info['parent_folder_id'])
            entity.code = py_unicode(info['code'])
            entity.label = py_unicode(re.sub('[-](\d{1,})', '', info['ui_code']).strip().upper())
            entity.title = py_unicode(info['title'])
            entity.genre = info['genre']
            entity.actor = info['actor']
            entity.site = py_unicode(info['site'])
            entity.studio = py_unicode(info['studio'])
            entity.country = py_unicode(info['country'])
            entity.poster_url = py_unicode(info['poster_url'])
            entity.fanart_url = py_unicode(info['fanart_url'])
            entity.trailer_url = py_unicode(info['trailer_url'])
            entity.year = info['year']
            entity.plot = py_unicode(info['plot'])
            entity.runtime = info['runtime']
            entity.orig_gdrive_path = py_unicode(info['orig_gdrive_path'])
            entity.save()
            return entity
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())


    @staticmethod
    def create_subfolder(rule_str, entity):
        try:
            rule_map = {
                    'ktv'  : ['status','genre','country', 'studio'],
                    'ftv'  : ['status','genre','country', 'studio'],
                    'movie': ['year' ,'genre','country'],
                    'avdvd': ['label' ,'actor'],
                    'avama': ['label' ,'actor']
                    }
            agent_type = entity.agent_type
            dict_entity = entity.as_dict()

            # AV의 경우 첫번째 배우만 처리함:TODO-추후 여러개 바로가기 처리 생성 고려필요
            if agent_type.startswith('av'):
                actor = entity.actor.split(u'|')[0]
                dict_entity['actor'] = actor

            for keyword in rule_map[entity.agent_type]:
                if rule_str.find('{'+keyword+'}') != -1:
                    rule_str = rule_str.replace('{'+keyword+'}', py_unicode(str(dict_entity[keyword])))

            rule_str = re.sub('{[a-z]+}', '', rule_str).strip()
            logger.debug('target subfolder name({})'.format(rule_str))

            parent_folder_id = entity.target_folder_id
            subfolders = rule_str.split(u'/')
            # exist: aaa/bbb
            # rule : aaa/bbb/ccc
            # sub  : aaa, bbb, 
            rm_target = []
            for folder in subfolders:
                sfentity = None
                sfentity = ModelSubFolderItem.get_by_rule_name_parent(entity.rule_id, folder, parent_folder_id)
                if sfentity != None: 
                    rm_target.append(folder)
                    parent_folder_id = sfentity.id
                else: break

            for folder in rm_target: subfolders.remove(folder)
            if len(subfolders) == 0:
                logger.debug('target subfolder already exists({})'.format(rule_str))
                return parent_folder_id

            logger.debug('create subfolder: (%s)', '/'.join(subfolders))
            for folder in subfolders:
                ret = LibGdrive.create_sub_folder(folder, parent_folder_id)
                if ret['ret'] == 'success':
                    f = ret['data']
                    sfentity = ModelSubFolderItem(f['name'], entity.rule_id, f['folder_id'], f['parent_folder_id'])
                    sfentity.save()
                    parent_folder_id = f['folder_id']
                else:
                    logger.error('failed to create sub-folder({})'.format(ret['msg']))
                    return None
            return parent_folder_id
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def change_text_for_use_filename(text):
        try:
            return re.sub('[\\/:*?\"<>|\[\]]', '', text).strip()
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_shortcut_name(entity):
        try:
            rule_map = {
                    'ktv'  : ['year','genre','studio'],
                    'ftv'  : ['year','genre','studio'],
                    'movie': ['year','genre','country'],
                    'avdvd': ['ui_code','actor','year','title', 'studio'],
                    'avama': ['ui_code','actor','year','title', 'studio'],
                    }

            key = '{}_shortcut_name_rule'.format(entity.agent_type)
            title = ScmUtil.change_text_for_use_filename(entity.title)
            name = ModelSetting.get(key)
            name = name.replace('{title}', title)
            name = name.replace('{orig}', entity.name)
            dict_entity = entity.as_dict()
            for keyword in rule_map[entity.agent_type]:
                if name.find('{'+keyword+'}') != -1:
                    if keyword == 'actor' and entity.agent_type.startswith('av'):
                        actor = entity.actor.split('|')[0]
                        name = name.replace('{'+keyword+'}', py_unicode(actor))
                    else:
                        name = name.replace('{'+keyword+'}', py_unicode(str(dict_entity[keyword])))

            return name

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def apply_meta(module_name, req):
        try:
            db_id = int(req.form['id'])
            if module_name == 'av': entity = ModelAvItem.get_by_id(db_id)
            else: entity = ModelTvMvItem.get_by_id(db_id)

            code = req.form['code']
            title = req.form['title']
            site = req.form['site']

            agent_type = entity.agent_type
            if module_name.endswith('tv'): agent_type = 'ktv' if code[0] == 'K' else 'ftv'
            info = ScmUtil.info_metadata(agent_type, code, title)
            if info == None:
                logger.error(u'메타정보 조회실패: %s:%s', agent_type, title)
                return { 'ret':'error', 'msg':'"{}"의 메타정보 조회실패.'.format(title) }

            entity.code = py_unicode(info['code'])
            if module_name != 'av': entity.status = info['status']
            #else: entity.ui_code = info['ui_code']
            entity.site = py_unicode(info['site'])
            entity.poster_url = py_unicode(info['poster_url'])
            entity.studio = py_unicode(info['studio'])
            entity.year = py_unicode(info['year'])
            entity.genre = py_unicode(info['genre'])
            entity.title = py_unicode(title)
            entity.country = py_unicode(info['country'])
            entity.save()
            
            return { 'ret':'success', 'msg':'"{}"의 메타정보 적용완료.'.format(entity.title) }

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'에러발생! 로그를 확인해주세요.' }

    @staticmethod
    def get_subchildren(fileid):
        try:
            ret = {}
            service = None
            service = LibGdrive.sa_authorize(ModelSetting.get('gdrive_auth_path'), return_service=True)
            if service == None: return {'ret':'error', 'msg':u'서비스계정 인증 실패.'}

            children = LibGdrive.get_children(fileid, ['id', 'name', 'mimeType', 'size'], service=service)
            if children == None:
                return { 'ret':'error', 'msg':'"{}"의 정보조회 실패.'.format(fileid) }

            children = sorted(children, key=lambda x:x['name'], reverse=True)
            ret['ret'] = 'success'
            ret['list'] = children
            return ret

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'에러발생! 로그를 확인해주세요.' }



    @staticmethod
    def get_children(module_name, db_id):
        try:
            ret = {}
            if module_name == 'av': entity = ModelAvItem.get_by_id(db_id)
            else: entity = ModelTvMvItem.get_by_id(db_id)

            service = None
            service = LibGdrive.sa_authorize(ModelSetting.get('gdrive_auth_path'), return_service=True)
            if service == None: return {'ret':'error', 'msg':u'서비스계정 인증 실패.'}

            children = LibGdrive.get_children(entity.folder_id, ['id', 'name', 'mimeType', 'size'], service=service)
            if children == None:
                return { 'ret':'error', 'msg':'"{}"의 정보조회 실패.'.format(entity.title) }

            children = sorted(children, key=lambda x:x['name'], reverse=True)

            if entity.agent_type.endswith('tv') and entity.shortcut_created == False:
                for child in children:
                    episode = None
                    episode = ModelSubItem.get_by_target_file_id(child['id'])
                    if episode != None:
                        child['in_plex'] = u'True'
                        child['shortcut_id'] = episode.shortcut_file_id
                    else: child['in_plex'] = u'False'

            ret['ret'] = 'success'
            ret['list'] = children
            return ret

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'에러발생! 로그를 확인해주세요.' }



    @staticmethod
    def refresh_info(module_name, req):
        try:
            db_id = int(req.form['id'])
            if module_name == 'av': entity = ModelAvItem.get_by_id(db_id)
            else: entity = ModelTvMvItem.get_by_id(db_id)
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

    @staticmethod
    def get_rule_names(module_name):
        try:
            if module_name == 'mv':
                rule_entities = ModelRuleItem.get_all_mv_entities()
            elif module_name == 'tv':
                rule_entities = ModelRuleItem.get_all_tv_entities()
            else: #av
                rule_entities = ModelRuleItem.get_all_av_entities()
            rule_names = list(set([x.name for x in rule_entities]))
            return rule_names
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_agent_types(module_name):
        try:
            if module_name == 'mv':
                rule_entities = ModelRuleItem.get_all_mv_entities()
            elif module_name == 'tv':
                rule_entities = ModelRuleItem.get_all_tv_entities()
            else: #av
                rule_entities = ModelRuleItem.get_all_av_entities()
                
            agent_types = list(set([x.agent_type for x in rule_entities]))
            return agent_types
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_all_agent_types():
        try:
            rule_entities = ModelRuleItem.get_all_agent_types()
            agent_types = list(set([x.agent_type for x in rule_entities]))
            return agent_types
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_all_genres(module_name):
        try:
            entities = ModelTvMvItem.get_all_genres(module_name)
            genres = [x.genre for x in entities]
            return list(filter(None, genres))
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_all_genres_by_rule_name(rule_name):
        try:
            entities = ModelTvMvItem.get_all_genres_by_rule_name(rule_name)
            genres = [x.genre for x in entities]
            return list(filter(None, genres))
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

            title, year = ScmUtil.get_title_year_from_dname(name)
            logger.debug('search_ktv: title(%s), year(%s)', title, year if year != None else '-')

            #if year != None: search_word = '{}|{}'.format(title, str(year))
            #else: search_word = title
            search_word = title

            return ScmUtil.search_metadata('ktv', search_word)

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
                    if ModelSetting.get_int('ktv_meta_result_limit_per_site') == count: continue
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
    def get_ftv_meta_list(metadata):
        try:
            meta_list = []
            sites = {}
            for m in metadata:
                #logger.debug(json.dumps(m, indent=2))
                if m['site'] in sites: sites[m['site']] = sites[m['site']] + 1
                else: sites[m['site']] = 1
                if ModelSetting.get_int('ftv_meta_result_limit_per_site') < sites[m['site']]: continue
                info = {}
                info['site'] = m['site']
                info['code'] = m['code']
                info['title'] = m['title']
                info['genre'] = m['genre']
                info['year'] = m['year'] if 'year' in m else 1900
                info['studio'] = m['studio']
                info['score'] = m['score']
                info['poster_url'] = m['image_url']
                meta_list.append(info)
                #logger.debug(json.dumps(info, indent=2))
            return meta_list
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

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
    def get_av_meta_list(metadata):
        meta_list = []
        count = 0
        for m in metadata:
            info = {}
            info['site'] = m['site']
            info['code'] = m['code']
            info['title'] = m['title_ko'] if m['title_ko'] != u'' else m['title']
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
                'ftv':['daum', 'tvdb', 'tmdb', 'watcha'],
                'movie':['naver', 'daum', 'tmdb', 'watcha', 'wavve', 'tving'],
                'avdvd':['dmm', 'javbus'],
                'avama':['mgstage', 'jav321', 'r18']}

        #TV
        title, year = ScmUtil.get_title_year_from_dname(title)
        logger.debug('agent_type: %s, title:%s', agent_type, title)
        if agent_type == 'ktv':
            metadata = agent_map[agent_type].search(title, manual=True)
        elif agent_type == 'movie':
            metadata = agent_map[agent_type].search(title, year, manual=True)
        elif agent_type == 'ftv':
            metadata = agent_map[agent_type].search(title, year, manual=True)
            #logger.debug(json.dumps(metadata, indent=2))
        elif agent_type == 'avdvd' or agent_type == 'avama':
            metadata = agent_map[agent_type].search(title, manual=True)
            #logger.debug(json.dumps(metadata, indent=2))

        if get_list:
            if agent_type == 'ktv': meta_list = ScmUtil.get_ktv_meta_list(metadata)
            elif agent_type == 'ftv': meta_list = ScmUtil.get_ftv_meta_list(metadata)
            elif agent_type == 'movie': meta_list = ScmUtil.get_movie_meta_list(metadata)
            else: meta_list = ScmUtil.get_av_meta_list(metadata)
            meta_list = sorted(meta_list, key=lambda x:x['score'], reverse=True)
            return {'ret':'success', 'data':meta_list}

        info = {}
        for site in site_map[agent_type]:
            if agent_type == 'ktv':
                if site in metadata:
                    if site != 'daum': r = metadata[site][0]
                    else: r = metadata[site]
                    #logger.debug('TEST: code:%s, title:%s', r['code'], r['title'])
                    info['code'] = r['code']
                    info['status'] = r['status'] if 'status' in r else 2
                    info['title'] = r['title']
                    info['site'] = r['site']
                    info['poster_url'] = r['image_url']
                    info['studio'] = r['studio']
                    info['year'] = r['year'] if 'year' in r else 1900
                    info['genre'] = r['genre'] if 'genre' in r else ''
                    break
            else:
                for r in metadata:
                    if agent_type.startswith('av'): info['ui_code'] = r['ui_code']
                    info['code'] = r['code']
                    info['status'] = 2
                    info['title'] = r['title']
                    info['site'] = r['site']
                    info['poster_url'] = r['image_url']
                    info['studio'] = u''
                    info['year'] = r['year']
                    info['genre'] = r['genre'] if 'genre' in r else ''
                    break
            """
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
            """

        return info
    
    
    @staticmethod
    def get_additional_prefix_by_code(agent_type, code):
        if agent_type.startswith('av'): entity = ModelAvItem.get_by_code(code)
        else: entity = ModelTvMvItem.get_by_code(code)
        rule = ModelRuleItem.get_by_id(entity.rule_id)
        return rule.additional_prefix

    @staticmethod
    def av_meta_info_map(metadata):
        info = {}
        info['code'] = py_unicode(metadata['code'])
        info['title'] = py_unicode(metadata['title'])
        info['genre'] = py_unicode(','.join(metadata['genre']))
        actor_list = []
        try:
            for actor in metadata['actor']:
                actor_list.append(actor['name']+'|'+actor['name2']+'|'+actor['originalname'])
        except: actor = u''
        info['actor'] = py_unicode(','.join(actor_list))
        info['site'] = py_unicode(metadata['site'])
        info['studio'] = py_unicode(metadata['studio'])
        info['country'] = py_unicode(metadata['country'][0])
        poster_url = u''
        for th in metadata['thumb']:
            if th['aspect'] == 'poster':
                if 'thumb' in th: poster_url = th['thumb'] if th['thumb'] != '' else th['value']
                else: poster_url = th['value']
                break
        if poster_url == u'': poster_url = metadata['thumb'][0]['value'] if 'thumb' in metadata else u''
        info['trailer_url'] = u''
        if 'extras' in metadata:
            try:
                for ex in metadata['extras']:
                    if ex['content_type'] == 'trailer':
                        info['trailer_url'] = py_unicode(ex['content_url'])
                        break
            except:
                info['trailer_url'] = u''
                
        info['poster_url'] = py_unicode(poster_url)
        info['fanart_url'] = py_unicode(metadata['fanart']) if 'fanart' in metadata else u''
        info['year'] = metadata['year'] if 'year' in metadata else 1900
        info['plot'] = py_unicode(metadata['plot']) if 'plot' in metadata else u''
        info['runtime'] = metadata['runtime'] if 'runtime' in metadata else 0
        #info['ui_code'] = metadata['originaltitle'] if 'originaltitle' in metadata else u''
        return info

    @staticmethod
    def info_metadata(agent_type, code, title):
        try:
            from metadata.logic_ktv import LogicKtv
            from metadata.logic_movie import LogicMovie
            from metadata.logic_ftv import LogicFtv
            from metadata.logic_ott_show import LogicOttShow
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
            title, year = ScmUtil.get_title_year_from_dname(title)
            metadata = {}
            if agent_type == 'ktv':
                metadata = agent_map[agent_type].info(code, title)
                if metadata == None:
                    import framework.wavve.api as Wavve
                    import framework.tving.api as Tving

                    if code[1] == 'W':
                        info = {}
                        r = Wavve.vod_programs_programid(code[2:])
                        if r == {}: return None
                        info['code'] = code
                        info['status'] = 1 if r['onair'] == "y" else 2
                        info['title'] = r['programtitle']
                        info['site'] = 'wavve'
                        info['poster_url'] = r['posterimage'] if 'posterimage' in r else ''
                        info['studio'] = r['cpname']
                        if 'firstreleasedate' in r:
                            if r['firstreleasedate'] == '': info['year'] = 1900
                            else: info['year'] = int(r['firstreleasedate'][:4])
                        else: info['year'] = 1900
                        info['genre'] = u'기타'
                        info['country'] = u'한국'
                        return info

                    # OTT SHOW
                    metadata = LogicOttShow(LogicOttShow).info(code)
                    #logger.debug(json.dumps(metadata, indent=2))
                    # TODO:
                    """
                    prefix = ScmUtil.get_additional_prefix_by_code(agent_type, code)
                    if prefix == u'': return None
                    tmp = prefix + ' ' + title
                    logger.debug('meta info failed add prefix(%s)', tmp)
                    metadata = agent_map[agent_type].info(code, tmp)
                    """
            else:
                metadata = agent_map[agent_type].info(code)

            if metadata == None:
                logger.error('failed to info metadata(%s:%s)', code, title)
                return None
            #debug
            #if agent_type == 'ftv':
                #logger.debug(json.dumps(metadata, indent=2))

            info = {}
            thumb = None
            if agent_type.startswith('av'):
                return ScmUtil.av_meta_info_map(metadata)
            elif agent_type == 'ktv':
                if 'thumb' in metadata:
                    thumbs = sorted(metadata['thumb'], key=lambda x:x['score'], reverse=True)
                    for th in thumbs:
                        if th['aspect'] == 'poster':
                            thumb = th
                            break
                    if thumb == None:
                        thumb = thumbs[0]
            elif agent_type == 'movie' or agent_type == 'ftv':
                if 'art' not in metadata: thumb = {'thumb':'', 'value':''}
                else:
                    for art in metadata['art']:
                        if art['aspect'] == 'poster':
                            thumb = art
                            break
                    if thumb == None:
                        if len(metadata['art']) > 0: thumb = metadata['art'][0]
                        else: thumb = {'thumb':'', 'value':''}


            info['code'] = metadata['code']
            if agent_type == 'ftv': info['status'] = 1 if metadata['status'] == 'Continuing' else 2
            else: info['status'] = metadata['status'] if 'status' in metadata else 2
            info['title'] = metadata['title']
            info['site'] = metadata['site']
            info['poster_url'] = thumb['value'] if thumb['thumb'] == "" else thumb['thumb']
            info['studio'] = metadata['studio']
            info['year'] = metadata['year'] if 'year' in metadata else 1900
            if 'genre' in metadata and len(metadata['genre']) > 0:
                #logger.debug(metadata['genre'])
                info['genre'] = re.sub('[/]','&', metadata['genre'][0])
            else: info['genre'] = u''
            if 'country' in metadata:
                #logger.debug(json.dumps(metadata['country'], indent=2))
                if type(metadata['country']) == type([]):
                    if len(metadata['country']) > 0: info['country'] = metadata['country'][0]
                    else: info['country'] = u''
                else: info['country'] = u'한국' if agent_type == 'ktv' else u''
            return info
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None
    
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
    def get_gdrive_path(plex_path):
        try:
            rules = ModelSetting.get('gdrive_plex_path_rule')
            if rules == u'' or rules.find('|') == -1:
                return plex_path
            if rules is not None:
                rules = rules.split(',')
                rules = sorted(rules, key=lambda x:len(x.split('|')[0]), reverse=True)
                for rule in rules:
                    tmp = rule.split('|')

                    if plex_path.startswith(tmp[1]):
                        ret = plex_path.replace(tmp[1], tmp[0])
                        # SJVA-PMS의 플랫폼이 다른 경우
                        if tmp[0][0] != tmp[1][0]:
                            if plex_path[0] == '/': # Linux   -> Windows
                                ret = ret.replace('/', '\\')
                            else:                  # Windows -> Linux
                                ret = ret.replace('\\', '/')
                        return ret
            return plex_path

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_local_path(gdrive_path):
        try:
            rules = ModelSetting.get('gdrive_local_path_rule')
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
    def get_rc_path(plex_path):
        try:
            ret = plex_path
            rules = ModelSetting.get('gdrive_plex_path_rule')
            if rules == u'' or rules.find('|') == -1:
                return ret
            if rules is not None:
                rules = rules.split(',')
                rules = sorted(rules, key=lambda x:len(x.split('|')[0]), reverse=True)
                for rule in rules:
                    tmp = rule.split('|')
                    if plex_path.startswith(tmp[1]):
                        ret = plex_path.replace(tmp[1], '').replace('\\\\', '\\').replace('\\', '/')
                        if ret[0] == '/': ret = ret[1:]
                        if sys.version_info[0] == 2:
                            return ret.encode('utf-8')
                        return ret
            
            if sys.version_info[0] == 2:
                return ret.encode('utf-8')
            return ret

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
    def get_entity_by_folder_id(agent_type, folder_id):
        if agent_type.startswith('av'):
            return ModelAvItem.get_by_folder_id(folder_id)
        return ModelTvMvItem.get_by_folder_id(folder_id)

    @staticmethod
    def get_title_year_from_dname(name):
        try:
            rx = r"\((?P<year>\d{4})?\)"
            match = re.compile(rx).search(name)
            if match: year = int(match.group('year'))
            else: year = None

            #title = re.sub('(\[(\w+|.+)\])', '', name)
            title = re.sub('(\[(\w+|.+)\])|\(\d{4}\)','',name)
            ################################################
            title = re.sub('[\\/:*?\"<>|\[\]]', '', title)
            return title.strip(), year
            
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_program_metadata_id(metakey, sub_type=None):
        try:
            import plex
            meta_id = metakey[metakey.rfind('/')+1:]

            for i in range(4):
                query = 'SELECT id,parent_id,metadata_type from metadata_items where id="{}"'.format(meta_id)
                ret = plex.LogicNormal.execute_query(query)
                if ret['ret'] != True: return None
                mid, pid, mtype = ret['data'][0].split('|')
                if sub_type != None and sub_type == 'season':
                    if mtype == '3':
                        meta_id = mid
                        break
                if mtype == '2':
                    meta_id = mid
                    break

                meta_id = pid
            logger.debug(u'get_program_metadata_id: {}'.format(meta_id))
            return '/library/metadata/{}'.format(meta_id)

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return None

    @staticmethod
    def change_excluded(module_name, db_id, action):
        try:
            if module_name == 'av': entity = ModelAvItem.get_by_id(db_id)
            else: entity = ModelTvMvItem.get_by_id(db_id)
            entity.excluded = True if action == 'add' else False
            entity.save()
            return {'ret':'success', 'msg':'제외목록 반영완료.'}
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return {'ret':'error', 'msg':'제외목록 반영실패.'}

    @staticmethod
    def send_message(ctype, msg):
        message_id = 'scmanager_request'
        m = u'[자료요청]\n'
        m += 'FROM: '+ SystemModelSetting.get('ddns') + '\n'
        m += '유형: '+ ctype + '\n'
        m += '내용: '+ msg
        ToolBaseNotify.send_message(m, message_id=message_id)
        return {'ret':'success', 'msg':'자료요청 전송 완료'}

    @staticmethod
    def check_subfolder(entity_id=None):
        try:
            service = None
            service = LibGdrive.sa_authorize(ModelSetting.get('gdrive_auth_path'), return_service=True)
            if service == None: return {'ret':'error', 'msg':u'서비스계정 인증 실패.'}
            rcount = 0
            if entity_id != None:
                sf = ModelSubFolderItem.get_by_id(entity_id)
                ret = LibGdrive.get_file_info(sf.folder_id, service=service)
                if (ret['ret'] != 'success' and ret['data'].find('HttpError 404') != -1) or (ret['ret'] == 'success' and ret['data']['trashed'] == True):
                    sf.delete(sf.id)
                return {'ret':'success', 'msg':u'삭제된 폴더아이템 정리 완료'}

            for sf in ModelSubFolderItem.get_all_entities():
                ret = LibGdrive.get_file_info(sf.folder_id, service=service)
                # 폴더가 삭제된 경우 처리
                if (ret['ret'] != 'success' and ret['data'].find('HttpError 404') != -1) or (ret['ret'] == 'success' and ret['data']['trashed'] == True):
                    logger.debug('[check_subfolder] remove deleted folder({},{})'.format(sf.name, sf.folder_id))
                    rcount = rcount + 1
                    sf.delete(sf.id)

            return {'ret':'success', 'msg':u'삭제된 폴더아이템 정리 완료({} 건)'.format(rcount)}
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return {'ret':'error', 'msg':u'폴더아이템 정리 실패.'}

    @staticmethod
    def check_subitem():
        try:
            service = None
            service = LibGdrive.sa_authorize(ModelSetting.get('gdrive_auth_path'), return_service=True)
            if service == None: return {'ret':'error', 'msg':u'서비스계정 인증 실패.'}
            rcount = 0
            for sub in ModelSubItem.get_all_entities():
                ret = LibGdrive.get_file_info(sub.shortcut_file_id, service=service)
                # 숏컷이 삭제된 경우 처리
                if (ret['ret'] != 'success' and ret['data'].find('HttpError 404') != -1) or (ret['ret'] == 'success' and ret['data']['trashed'] == True):
                    logger.debug('[check_subitem] remove deleted folder({},{})'.format(sub.name, sub.shortcut_file_id))
                    rcount = rcount + 1
                    sub.delete(sub.id)

            return {'ret':'success', 'msg':u'삭제된 시즌/에피소드 아이템 정리 완료({} 건)'.format(rcount)}
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return {'ret':'error', 'msg':u'시즌/에피소드 아이템 정리 실패.'}

    @staticmethod
    def get_remote_by_name(remote_name):
        from tool_base import ToolRclone
        try:
            remotes = ToolRclone.config_list()
            if remote_name in remotes:
                return remotes[remote_name]
            return None
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    def get_headers(headers, kind, token):
        try:
            chunk = ModelSetting.get('default_chunk')
            if kind == "video":
                if 'Range' not in headers or headers['Range'].startswith('bytes=0-'):
                    headers['Range'] = f"bytes=0-{chunk}"
            else:
                if 'Range' in headers: del(headers['Range'])
            headers['Authorization'] = f"Bearer {token}"
            headers['Connection'] = 'keep-alive'
            if 'Host' in headers: del(headers['Host'])
            if 'X-Forwarded-Scheme' in headers: del(headers['X-Forwarded-Scheme'])
            if 'X-Forwarded-Proto' in headers: del(headers['X-Forwarded-Proto'])
            if 'X-Forwarded-For' in headers: del(headers['X-Forwarded-For'])
            if 'Cookie' in headers: del(headers['Cookie'])
            return headers
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def proxy_handler(request):
        try:
            base_url = 'https://www.googleapis.com/drive/v3/files/{fileid}?alt=media'

            fileid = request.args.get('f', None)
            remote_name = request.args.get('r', ModelSetting.get('default_remote'))
            kind = request.args.get('k', 'video')
            name = request.args.get('n', None)
            logger.debug(f'{fileid},{remote_name},{kind},{name}')

            remote = ScmUtil.get_remote_by_name(remote_name)
            if not remote:
                logger.error(f'failed to get remote({remote_name})')
                return Response(f'failed to get remote{remote_name})', 401, content_type='text/html')

            token = LibGdrive.get_access_token_by_remote(remote)
            if not token:
                logger.error(f'failed to get access_token({remote_name})')
                return Response(f'failed to get access_token{remote_name})', 401, content_type='text/html', direct_paththrough=True)

            headers = ScmUtil.get_headers(dict(request.headers), kind, token)
            url = base_url.format(fileid=fileid)
            r = requests.get(url, headers=headers, stream=True)
            # reponse header reset
            if name != None and name.endswith('.srt'):
                r.headers['Content-Type'] = 'text/plain'
                r.headers['Content-Disposition'] = f'inline; filename="{name}"'

            chunk = ModelSetting.get_int('default_chunk')
            rv = Response(r.iter_content(chunk_size=chunk), r.status_code, content_type=r.headers['Content-Type'], direct_passthrough=True)
            rv.headers.add('Content-Range', r.headers.get('Content-Range'))
            return rv
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
