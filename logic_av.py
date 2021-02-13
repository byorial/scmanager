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
            arg['categories'] = ','.join(LogicAv.get_av_rule_names())
            arg['agent_types'] = ','.join(LogicAv.get_av_agent_types())
        return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)


    def process_ajax(self, sub, req):
        try:
            if sub == 'web_list':
                ret = ModelAvItem.web_list(req)
            elif sub == 'create_shortcut':
                entity_id = int(req.form['id'])
                ret = LogicAv.create_shortcut(entity_id)
            return jsonify(ret)

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})

    @staticmethod
    def meta_info_map(metadata):
        info = {}
        info['code'] = py_unicode(metadata['code'])
        info['ui_code'] = py_unicode(metadata['ui_code'])
        info['title'] = py_unicode(metadata['title'])
        info['genre'] = py_unicode(','.join(metadata['genre']))
        actor_list = []
        for actor in metadata['actor']:
            actor_list.append(actor['name']+'|'+actor['name2']+'|'+actor['originalname'])
        info['actor'] = py_unicode(','.join(actor_list))
        info['site'] = py_unicode(metadata['site'])
        info['studio'] = py_unicode(metadata['studio'])
        info['country'] = py_unicode(metadata['country'][0])
        poster_url = u''
        for th in metadata['thumb']:
            if th['aspect'] == 'poster':
                poster_url = th['thumb'] if th['thumb'] != "" else th['value']
                break
        if poster_url == u'': poster_url = metadata['thumb'][0]['value'] if 'thumb' in metadata else u''
        info['trailer_url'] = u''
        if 'extras' in metadata:
            for ex in metadata['extras']:
                if ex['content_type'] == 'trailer':
                    info['trailer_url'] = py_unicode(ex['content_url'])
                    break
        info['poster_url'] = py_unicode(poster_url)
        info['fanart_url'] = py_unicode(metadata['fanart']) if 'fanart' in metadata else u''
        info['year'] = metadata['year']
        info['plot'] = py_unicode(metadata['plot'])
        info['runtime'] = metadata['runtime']
        return info

    @staticmethod
    def create_av_entity(info):
        try:
            entity = ModelAvItem(info['ui_code'])
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
            entity.save()
            return entity
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

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

    #########################################################

class ModelAvItem(db.Model):
    __tablename__ = '%s_av_item' % package_name
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
    shortcut_count = db.Column(db.Integer)
    shortcut_folder_id = db.Column(db.String)
    shortcut_name = db.Column(db.String)
    gdrive_path = db.Column(db.String)
    plex_path = db.Column(db.String)

    # info from gdrive
    name = db.Column(db.String)
    mime_type = db.Column(db.String)
    folder_id = db.Column(db.String)
    parent_folder_id = db.Column(db.String)

    # info from metadata
    code = db.Column(db.String)
    ui_code = db.Column(db.String)
    title = db.Column(db.String)
    genre = db.Column(db.String)
    actor = db.Column(db.String)
    site = db.Column(db.String)
    studio = db.Column(db.String)
    country = db.Column(db.String)
    poster_url = db.Column(db.String)
    fanart_url = db.Column(db.String)
    trailer_url = db.Column(db.String)
    year = db.Column(db.Integer)
    plot = db.Column(db.String)
    runtime = db.Column(db.Integer)

    def __init__(self, ui_code):
        self.created_time = datetime.now()
        self.ui_code = py_unicode(ui_code)
        self.shortcut_created = False
        self.shortcut_count = 0

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
    def get_by_name(cls, name):
        return db.session.query(cls).filter_by(name=name).first()

    @classmethod
    def get_by_code(cls, code):
        return db.session.query(cls).filter_by(code=code).first()

    @classmethod
    def get_by_ui_code(cls, ui_code):
        return db.session.query(cls).filter_by(ui_code=ui_code).first()

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
            query = cls.make_query(search=search, rule_name=rule_name, shortcut_status=shortcut_status)
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


