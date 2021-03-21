import os, sys, traceback, re, json, threading, time, shutil
from framework import db, py_unicode
from framework.util import Util
from sqlalchemy import or_, and_, func, not_, desc
from datetime import datetime
from .plugin import P

logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

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
    use_auto_create_shortcut = db.Column(db.Boolean)

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
        self.use_auto_create_shortcut = info['use_auto_create_shortcut']
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
    def delete(cls, id):
        db.session.query(cls).filter_by(id=id).delete()
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
    def get_all_entities(cls):
        return db.session.query(cls).all()

    @classmethod
    def get_all_entities_except_av(cls):
        query = db.session.query(cls)
        return query.filter(not_(cls.agent_type.like('av%'))).all()

    @classmethod
    def get_all_tv_entities(cls):
        query = db.session.query(cls)
        return query.filter(cls.agent_type.like('%tv')).all()

    @classmethod
    def get_all_mv_entities(cls):
        return db.session.query(cls).filter_by(agent_type='movie').all()

    @classmethod
    def get_all_av_entities(cls):
        query = db.session.query(cls)
        return query.filter(cls.agent_type.like('av%')).all()

    @classmethod
    def get_all_entities_by_agent_type(cls, agent_type):
        query = db.session.query(cls)
        return query.filter(cls.agent_type == agent_type).all()

    @classmethod
    def get_all_agent_types(cls):
        use_av = ModelSetting.get_bool('use_av')
        query = db.session.query(cls)
        if use_av == False:
            query = query.filter(not_(cls.agent_type.like('av%')))
        return query.group_by(cls.agent_type).order_by(func.count(cls.id).desc()).all()

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
        use_av = ModelSetting.get_bool('use_av')
        query = db.session.query(cls)
        if use_av == False: query = query.filter(not_(cls.agent_type.like('av%')))
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



class ModelTvMvItem(db.Model):
    __tablename__ = '%s_tvmv_item' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    updated_time = db.Column(db.DateTime)
    reserved = db.Column(db.JSON)

    # basic info
    rule_name = db.Column(db.String)   # from category_rules
    rule_id = db.Column(db.Integer)
    agent_type = db.Column(db.String) # ktv, ftv, movie, av?
    root_folder_id = db.Column(db.String)
    target_folder_id = db.Column(db.String)
    orig_gdrive_path = db.Column(db.String)

    shortcut_created = db.Column(db.Boolean)
    shortcut_folder_id = db.Column(db.String)
    gdrive_path = db.Column(db.String)
    local_path = db.Column(db.String)
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

    # for plex
    plex_section_id = db.Column(db.String)
    plex_metadata_id = db.Column(db.String)

    excluded = db.Column(db.Boolean)

    def __init__(self, name, folder_id, rule_name, rule_id):
        self.created_time = datetime.now()
        self.name = py_unicode(name)
        self.folder_id = py_unicode(folder_id)
        self.rule_name = py_unicode(rule_name)
        self.rule_id = rule_id
        self.shortcut_created = False
        self.updated_time = datetime.now()
        self.excluded = False

    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        ret = {x.name: getattr(self, x.name) for x in self.__table__.columns}
        ret['created_time'] = self.created_time.strftime('%m-%d %H:%M:%S') 
        ret['updated_time'] = self.updated_time.strftime('%m-%d %H:%M:%S') 
        return ret
    
    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def delete(cls, id):
        db.session.query(cls).filter_by(id=id).delete()
        db.session.commit()

    @classmethod
    def delete_items_by_rule_id(cls, rule_id):
        db.session.query(cls).filter_by(rule_id=rule_id).delete()
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
    def get_shortcut_created_entities(cls, rule_id):
        return db.session.query(cls).filter(and_(cls.rule_id==rule_id, cls.shortcut_created==True)).all()

    @classmethod
    def get_all_entities(cls):
        return db.session.query(cls).all()

    @classmethod
    def get_onair_entities(cls):
        return db.session.query(cls).filter_by(status=1).all()

    @classmethod
    def get_entities_by_rule_id(cls, rule_id):
        return db.session.query(cls).filter_by(rule_id=rule_id).all()

    @classmethod
    def get_item_count(cls, rule_id):
        return db.session.query(cls).filter_by(rule_id=rule_id).count()

    @classmethod
    def get_shortcut_count(cls, rule_id):
        return db.session.query(cls).filter(and_(cls.rule_id==rule_id, cls.shortcut_created==True)).count()

    @classmethod
    def get_onair_entities_with_shortcut(cls):
        query = db.session.query(cls)
        query = query.filter(cls.status == 1)
        query = query.filter(cls.shortcut_created == True)
        return query.all()

    @classmethod
    def get_all_genres(cls, module_name):
        query = db.session.query(cls)
        if module_name == 'mv':
            query = query.filter(cls.agent_type=='movie')
        else: # ktv/ftv
            query = query.filter(or_(cls.agent_type=='ktv', cls.agent_type=='ftv'))
        return query.group_by(cls.genre).order_by(func.count(cls.id).desc()).all()

    @classmethod
    def get_all_entities_group_by_parent(cls, rule_id):
        query = db.session.query(cls)
        return query.filter(cls.rule_id==rule_id).group_by(cls.parent_folder_id).all()

    @classmethod
    def get_item_count(cls, rule_id):
        return db.session.query(cls).filter_by(rule_id=rule_id).count()

    @classmethod
    def update_all_rows_by_rule_id(cls, rule_id, col_values):
        query = db.session.query(cls)
        query = query.filter(cls.rule_id==rule_id)
        query.update(col_values)
        db.session.commit()

    @classmethod
    def web_list(cls, module_name, req):
        try:
            ret = {}
            page = 1
            page_size = 30
            job_id = ''
            search = ''
            category = ''
	    genre = 'all'
            if 'page' in req.form:
                page = int(req.form['page'])
            if 'search_word' in req.form:
                search = req.form['search_word']
	    if 'genre' in req.form:
                genre = req.form['genre']
            rule_name = req.form['category'] if 'category' in req.form else 'all'
            status_option = req.form['status_option'] if 'status_option' in req.form else 'all'
            query = cls.make_query(module_name=module_name, genre=genre, search=search, rule_name=rule_name, status_option=status_option)
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
    def make_query(cls, module_name='', genre='all', search='', rule_name='all', status_option='all', order='desc'):
        query = db.session.query(cls)
        if module_name != '':
            if module_name == 'movie': query = query.filter(cls.agent_type == 'movie')
            else: query = query.filter(cls.agent_type.like('%tv'))
	if genre != 'all': query = query.filter(cls.genre == genre)
        if search is not None and search != '':
            if search.find('|') != -1:
                tmp = search.split('|')
                conditions = []
                for tt in tmp:
                    if tt != '':
                        conditions.append(cls.title.like('%'+tt.strip()+'%') )
                        conditions.append(cls.name.like('%'+tt.strip()+'%') )
                query = query.filter(or_(*conditions))
            elif search.find(',') != -1:
                tmp = search.split(',')
                conditions = []
                for tt in tmp:
                    if tt != '':
                        conditions.append(cls.title.like('%'+tt.strip()+'%') )
                        conditions.append(cls.name.like('%'+tt.strip()+'%') )
                        query = query.filter(or_(*conditions))
            else:
                query = query.filter(or_(cls.title.like('%'+search+'%'), cls.name.like('%'+search+'%')))

        if rule_name != 'all':
            query = query.filter(cls.rule_name == rule_name)

        if status_option == 'excluded':
            query = query.filter(cls.excluded == True)
        elif status_option == 'subitem':
            episodes = ModelSubItem.get_all_entities_group_by_entity_id()
            entity_ids = list(set([x.entity_id for x in episodes]))
            query = query.filter(cls.id.in_(entity_ids))
        else:
            query = query.filter(cls.excluded == False)
            if status_option != 'all':
                if status_option == 'true': query = query.filter(cls.shortcut_created == True)
                elif status_option == 'onair': query = query.filter(cls.status == 1)
                elif status_option == 'ended': query = query.filter(cls.status == 2)
                else: query = query.filter(cls.shortcut_created == False)

        if order == 'desc':
            query = query.order_by(desc(cls.updated_time))
            #query = query.order_by(desc(cls.id))
        else:
            query = query.order_by(desc(cls.updated_time))
            #query = query.order_by(cls.id)

        return query 



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
    orig_gdrive_path = db.Column(db.String)

    shortcut_created = db.Column(db.Boolean)
    shortcut_count = db.Column(db.Integer)
    shortcut_folder_id = db.Column(db.String)
    shortcut_name = db.Column(db.String)
    gdrive_path = db.Column(db.String)
    local_path = db.Column(db.String)
    plex_path = db.Column(db.String)

    # info from gdrive
    name = db.Column(db.String)
    mime_type = db.Column(db.String)
    folder_id = db.Column(db.String)
    parent_folder_id = db.Column(db.String)

    # info from metadata
    code = db.Column(db.String)
    ui_code = db.Column(db.String)
    label = db.Column(db.String)
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

    # for plex
    plex_section_id = db.Column(db.String)
    plex_metadata_id = db.Column(db.String)

    excluded = db.Column(db.Boolean)

    def __init__(self, ui_code, folder_id):
        self.created_time = datetime.now()
        self.ui_code = py_unicode(ui_code)
        self.folder_id = py_unicode(folder_id)
        self.shortcut_created = False
        self.shortcut_count = 0
        self.excluded = False

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
    def delete(cls, id):
        db.session.query(cls).filter_by(id=id).delete()
        db.session.commit()

    @classmethod
    def delete_items_by_rule_id(cls, rule_id):
        db.session.query(cls).filter_by(rule_id=rule_id).delete()
        db.session.commit()

    @classmethod
    def get_by_id(cls, id):
        return db.session.query(cls).filter_by(id=id).first()

    @classmethod
    def get_by_folder_id(cls, folder_id):
        return db.session.query(cls).filter_by(folder_id=folder_id).first()
    
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
    def get_entities_by_rule_id(cls, rule_id):
        return db.session.query(cls).filter_by(rule_id=rule_id).all()

    @classmethod
    def get_item_count(cls, rule_id):
        return db.session.query(cls).filter_by(rule_id=rule_id).count()

    @classmethod
    def get_shortcut_count(cls, rule_id):
        return db.session.query(cls).filter(and_(cls.rule_id==rule_id, cls.shortcut_created==True)).count()

    @classmethod
    def get_shortcut_created_entities(cls, rule_id):
        return db.session.query(cls).filter(and_(cls.rule_id==rule_id, cls.shortcut_created==True)).all()

    @classmethod
    def get_all_entities_group_by_parent(cls, rule_id):
        query = db.session.query(cls)
        return query.filter(cls.rule_id==rule_id).group_by(cls.parent_folder_id).all()

    @classmethod
    def update_all_rows_by_rule_id(cls, rule_id, col_values):
        query = db.session.query(cls)
        query = query.filter(cls.rule_id==rule_id)
        query.update(col_values)
        db.session.commit()

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
            status_option = req.form['status_option'] if 'status_option' in req.form else 'all'
            query = cls.make_query(search=search, rule_name=rule_name, status_option=status_option)
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
    def make_query(cls, search='', rule_name='all', status_option='all', order='desc'):
        query = db.session.query(cls)
        #if agent_type != 'all': query = query.filter(cls.agent_type == agent_type)
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
                query = query.filter(or_(cls.title.like('%'+search+'%'), cls.name.like('%'+search+'%'), cls.actor.like('%'+search+'%')))

        if rule_name != 'all':
            query = query.filter(cls.rule_name == rule_name)

        if status_option == 'excluded':
            query = query.filter(cls.excluded == True)
        else:
            query = query.filter(cls.excluded == False)
            if status_option != 'all':
                if status_option == 'true': query = query.filter(cls.shortcut_created == True)
                else: query = query.filter(cls.shortcut_created == False)

        if order == 'desc':
            query = query.order_by(desc(cls.id))
        else:
            query = query.order_by(desc(cls.id))

        return query 

class ModelSubFolderItem(db.Model):
    __tablename__ = '%s_subfolder_item' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    reserved = db.Column(db.JSON)

    name = db.Column(db.String)
    rule_id = db.Column(db.Integer)
    folder_id = db.Column(db.String)
    parent_folder_id = db.Column(db.String)

    def __init__(self, name, rule_id, folder_id, parent_folder_id):
        self.created_time = datetime.now()

        self.name = py_unicode(name)
        self.rule_id = rule_id
        self.folder_id = py_unicode(folder_id)
        self.parent_folder_id = py_unicode(parent_folder_id)

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
    def delete(cls, id):
        db.session.query(cls).filter_by(id=id).delete()
        db.session.commit()

    @classmethod
    def get_by_id(cls, id):
        return db.session.query(cls).filter_by(id=id).first()
    
    @classmethod
    def get_by_name(cls, name):
        return db.session.query(cls).filter_by(name=name).first()

    @classmethod
    def get_by_rule_name_parent(cls, rule_id, name, parent_folder_id):
        query = db.session.query(cls)
        query = query.filter(cls.rule_id == rule_id)
        query = query.filter(cls.name == name)
        query = query.filter(cls.parent_folder_id == parent_folder_id)
        return query.first()
 
    @classmethod
    def get_by_folder_id(cls, folder_id):
        return db.session.query(cls).filter_by(folder_id=folder_id).first()

    @classmethod
    def get_all_entities(cls):
        return db.session.query(cls).all()

    @classmethod
    def get_entities_by_rule_id(cls, rule_id):
        return db.session.query(cls).filter_by(rule_id=rule_id).all()



class ModelSubItem(db.Model):
    __tablename__ = '%s_sub_item' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    reserved = db.Column(db.JSON)

    # basic info
    name = db.Column(db.String)
    entity_id = db.Column(db.Integer)
    sub_type = db.Column(db.String)
    agent_type = db.Column(db.String)
    target_file_id = db.Column(db.String)
    shortcut_file_id = db.Column(db.String)
    parent_folder_id = db.Column(db.String)

    # for plex
    plex_path = db.Column(db.String)
    plex_section_id = db.Column(db.String)
    plex_metadata_id = db.Column(db.String)

    def __init__(self, name, entity_id, agent_type, sub_type):
        self.created_time = datetime.now()
        self.name = py_unicode(name)
        self.entity_id = entity_id
        self.sub_type = sub_type
        self.agent_type = py_unicode(agent_type)

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
    def delete(cls, id):
        db.session.query(cls).filter_by(id=id).delete()
        db.session.commit()

    @classmethod
    def get_by_id(cls, id):
        return db.session.query(cls).filter_by(id=id).first()
    
    @classmethod
    def get_by_target_file_id(cls, target_file_id):
        return db.session.query(cls).filter_by(target_file_id=target_file_id).first()

    @classmethod
    def get_by_plex_path(cls, plex_path):
        return db.session.query(cls).filter_by(plex_path=plex_path).first()

    @classmethod
    def get_by_shortcut_file_id(cls, shortcut_file_id):
        return db.session.query(cls).filter_by(shortcut_file_id=shortcut_file_id).first()

    @classmethod
    def get_entities_by_entity_id(cls, entity_id):
        return db.session.query(cls).filter_by(entity_id=entity_id).all()

    @classmethod
    def get_all_entities(cls):
        return db.session.query(cls).all()

    @classmethod
    def get_item_count(cls, entity_id):
        return db.session.query(cls).filter_by(entity_id=entity_id).count()

    @classmethod
    def get_all_entities_group_by_entity_id(cls):
        return db.session.query(cls).group_by(cls.entity_id).order_by(func.count(cls.id).desc()).all()

    @classmethod
    def web_list(cls, module_name, req):
        try:
            ret = {}
            page = 1
            page_size = 30
            job_id = ''
            search = ''
            category = ''
	    genre = 'all'
            if 'page' in req.form:
                page = int(req.form['page'])
            if 'search_word' in req.form:
                search = req.form['search_word']
	    if 'genre' in req.form:
                genre = req.form['genre']
            rule_name = req.form['category'] if 'category' in req.form else 'all'
            status_option = req.form['status_option'] if 'status_option' in req.form else 'all'
            query = cls.make_query(module_name=module_name, genre=genre, search=search, rule_name=rule_name, status_option=status_option)
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
    def make_query(cls, module_name='', genre='all', search='', rule_name='all', status_option='all', order='desc'):
        query = db.session.query(cls)
        if module_name != '':
            if module_name == 'movie': query = query.filter(cls.agent_type == 'movie')
            else: query = query.filter(cls.agent_type.like('%tv'))
	if genre != 'all': query = query.filter(cls.genre == genre)
        if search is not None and search != '':
            if search.find('|') != -1:
                tmp = search.split('|')
                conditions = []
                for tt in tmp:
                    if tt != '':
                        conditions.append(cls.title.like('%'+tt.strip()+'%') )
                        conditions.append(cls.name.like('%'+tt.strip()+'%') )
                query = query.filter(or_(*conditions))
            elif search.find(',') != -1:
                tmp = search.split(',')
                conditions = []
                for tt in tmp:
                    if tt != '':
                        conditions.append(cls.title.like('%'+tt.strip()+'%') )
                        conditions.append(cls.name.like('%'+tt.strip()+'%') )
                        query = query.filter(or_(*conditions))
            else:
                query = query.filter(or_(cls.title.like('%'+search+'%'), cls.name.like('%'+search+'%')))

        if rule_name != 'all':
            query = query.filter(cls.rule_name == rule_name)

        if status_option == 'excluded':
            query = query.filter(cls.excluded == True)
        else:
            query = query.filter(cls.excluded == False)
            if status_option != 'all':
                if status_option == 'true': query = query.filter(cls.shortcut_created == True)
                elif status_option == 'onair': query = query.filter(cls.status == 1)
                elif status_option == 'ended': query = query.filter(cls.status == 2)
                else: query = query.filter(cls.shortcut_created == False)

        if order == 'desc':
            query = query.order_by(desc(cls.updated_time))
            #query = query.order_by(desc(cls.id))
        else:
            query = query.order_by(desc(cls.updated_time))
            #query = query.order_by(cls.id)

        return query 
