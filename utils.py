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
from .models import ModelRuleItem, ModelTvMvItem, ModelAvItem, ModelSubFolderItem

# 패키지
from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

#########################################################

class ScmUtil(LogicModuleBase):
    RuleHandlerThread = None
    RuleJobQueue = None

    PlexScannerThread = None
    PlexScannerQueue = None


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
            ### TODO
            info['use_subfolder'] = False
            info['subfolder_rule'] = u''
            #info['use_subfolder'] = True if req.form['use_subfolder'] == 'True' else False
            #info['subfolder_rule'] = py_urllib.unquote(req.form['subfolder_rule'])
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
            ### TODO
            entity.use_subfolder = False
            entity.subfolder_rule = u''
            #entity.use_subfolder = True if req.form['curr_use_subfolder'] == 'True' else False
            #entity.subfolder_rule = py_urllib.unquote(req.form['curr_subfolder_rule'])
            entity.use_plex = True if req.form['curr_use_plex'] == 'True' else False
            entity.use_schedule = True if req.form['curr_use_schedule'] == 'True' else False
            entity.save()
            return {'ret':'success', 'msg':u'{n} 항목이 수정 되었습니다.'.format(n=entity.name)} 
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def create_tvmv_entity(info):
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
            entity.orig_gdrive_path = py_unicode(info['orig_gdrive_path'])
            entity.save()
            return entity
        
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def create_av_entity(info):
        try:
            entity = ModelAvItem(info['ui_code'], info['folder_id'])
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
                    'ktv'  : ['year' ,'genre','studio'],
                    'ftv'  : ['year' ,'genre','studio'],
                    'movie': ['year' ,'genre','country'],
                    'avdvd': ['label' ,'actor'],
                    'avama': ['label' ,'actor'],
                    }
            agent_type == entity.agent_type
            dict_entity = entity.as_dict()

            for keyword in rule_map[entity.agent_type]:
                if rule_str.find('{'+keyword+'}') != -1:
                    rule_str = rule_str.replace('{'+keyword+'}', py_unicode(str(dict_entity[keyword])))

            logger.debug('target subfolder name({})'.format(rule_str))

            parent_folder_id = entity.target_folder_id
            subfolders = rule_str.split('/')
            # exist: aaa/bbb
            # rule : aaa/bbb/ccc
            # sub  : aaa, bbb, 
            rm_target = []
            for folder in subfolders:
                sfentity = None
                sfentity = get_by_rule_name_parent(entity.rule_id, folder, parent_folder_id)
                if sfentity != None: 
                    rm_target.append(folder)
                    parent_folder_id = sfentity.id

            for folder in rm_target: subfolders.remove(folder)
            if len(subfolders) == 0:
                logger.debug('target subfolder already exists({})'.format(rule_str))
                return parent_folder_id

            subfolder_name = u'/'.join(subfolders)
            ret = LibGdrive.create_sub_folder(subfolder_name, parent_folder_id)

            if ret['ret'] == 'success':
                for f in ret['data']:
                    sfentity = ModelSubFolderItem(f['name'], entity.rule_id, f['folder_id'], f['parent_folder_id'])
                    sfentity.save()
                # 최하위 폴더ID 리턴   
                return sfentity.folder_id
            else: return None

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
                    'ktv'  : ['year' ,'genre','studio'],
                    'ftv'  : ['year' ,'genre','studio'],
                    'movie': ['year' ,'genre','country'],
                    'avdvd': ['code' ,'year' ,'genre','studio'],
                    'avama': ['code' ,'year' ,'genre','studio'],
                    }

            key = '{}_shortcut_name_rule'.format(entity.agent_type)
            title = ScmUtil.change_text_for_use_filename(entity.title)
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
    def apply_meta(module_name, req):
        try:
            db_id = int(req.form['id'])
            if module_name == 'av':
                entity = ModelAvItem.get_by_id(db_id)
            else:
                entity = ModelTvMvItem.get_by_id(db_id)

            code = req.form['code']
            title = req.form['title']
            site = req.form['site']

            info = ScmUtil.info_metadata(entity.agent_type, code, title)
            if info == None:
                logger.error(u'메타정보 조회실패: %s:%s', rule.agent_type, title)
                return { 'ret':'error', 'msg':'"{}"의 메타정보 조회실패.'.format(title) }

            entity.code = py_unicode(info['code'])
            if module_name != 'av': entity.status = info['status']
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
    def get_children(module_name, db_id):
        try:
            ret = {}
            if module_name == 'av': entity = ModelAvItem.get_by_id(db_id)
            else: entity = ModelTvMvItem.get_by_id(db_id)

            children = LibGdrive.get_children(entity.folder_id, ['id', 'name', 'mimeType', 'size'])
            if children == None:
                return { 'ret':'error', 'msg':'"{}"의 정보조회 실패.'.format(entity.title) }

            children = sorted(children, key=lambda x:x['name'], reverse=True)
            ret['ret'] = 'success'
            ret['list'] = children
            return ret

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
            genres = list(set([x.genre for x in entities]))
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
        title, year = ScmUtil.get_title_year_from_dname(title)
        if agent_type == 'ktv':
            metadata = agent_map[agent_type].search(title, manual=True)
        elif agent_type == 'movie':
            metadata = agent_map[agent_type].search(title, year, manual=True)
        elif agent_type == 'avdvd':
            metadata = agent_map[agent_type].search(title, all_find=True, do_trans=True)
            #logger.debug(json.dumps(metadata, indent=2))

        if get_list:
            if agent_type == 'ktv': meta_list = ScmUtil.get_ktv_meta_list(metadata)
            else: meta_list = ScmUtil.get_movie_meta_list(metadata)
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
        return info

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
        title, year = ScmUtil.get_title_year_from_dname(title)
        metadata = {}
        if agent_type == 'ktv':
            metadata = agent_map[agent_type].info(code, title)
            if metadata == None:
                prefix = ScmUtil.get_additional_prefix_by_code(agent_type, code)
                if prefix == u'': return None
                tmp = prefix + ' ' + title
                logger.debug('meta info failed add prefix(%s)', tmp)
                metadata = agent_map[agent_type].info(code, tmp)
        else:
            metadata = agent_map[agent_type].info(code)


        #debug
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
        elif agent_type == 'movie':
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
        info['status'] = metadata['status'] if 'status' in metadata else 2
        info['title'] = metadata['title']
        info['site'] = metadata['site']
        info['poster_url'] = thumb['value'] if thumb['thumb'] == "" else thumb['thumb']
        info['studio'] = metadata['studio']
        info['year'] = metadata['year'] if 'year' in metadata else 1900
        if 'genre' in metadata and len(metadata['genre']) > 0:
            logger.debug(metadata['genre'])
            info['genre'] = re.sub('[/]','&', metadata['genre'][0])
        else: info['genre'] = u''
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
            return title.strip(), year
            
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_program_metadata_id(metakey):
        try:
            import plex
            meta_id = metakey[metakey.rfind('/')+1:]

            for i in range(4):
                query = 'SELECT parent_id from metadata_items where id="{}"'.format(meta_id)
                ret = plex.LogicNormal.execute_query(query)
                if ret['ret'] != True: return None
                if ret['data'][0] == u'': break
                meta_id = ret['data'][0]

            return '/library/metadata/{}'.format(meta_id)

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return None
