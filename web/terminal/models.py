from typing import Self
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from colorfield.fields import ColorField
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from encrypted_model_fields.fields import EncryptedCharField
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from abc import ABCMeta, abstractmethod
from django.urls import reverse
from terminal.ssh import SSHModule
from django.core.cache import cache
from asgiref.sync import sync_to_async
from functools import wraps
from terminal.errors import ReconnectRequired
import secrets
from web.settings import COLOR_PALETTE
from django.core.exceptions import ImproperlyConfigured
from terminal.apps import TerminalConfig

def strip_object(data: dict):
    return  {k: str(v).strip() if v else None for k, v in data.items()}

def strip_args(*args_to_strip: list[str]):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            parsed_kwargs = {}
            for key, value in kwargs.items():
                if key in args_to_strip:
                    parsed_kwargs[key] = value

            for key in parsed_kwargs:
                kwargs.pop(key)

            return func(
                *args,
                **kwargs,
                **strip_object(parsed_kwargs)
            )

        return wrapper
    return decorator


class AccManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('The username field must be set')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        return self.create_user(username, password, **extra_fields)

class AccountData(AbstractBaseUser, PermissionsMixin):
    saved_hosts: 'SavedHost'
    sessions: 'SessionsList'

    email = models.EmailField(max_length=40, unique=False, help_text='The email address of the user.')
    first_name = models.CharField(max_length=30, blank=True, null=True, help_text='The first name of the user.')
    last_name = models.CharField(max_length=30, blank=True, null=True, help_text='The last name of the user.')
    username = models.CharField(max_length=30, unique=True, help_text='The username of the user.')
    is_active = models.BooleanField(default=True, help_text='Designates whether this user should be treated as active.')
    is_staff = models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.')
    is_superuser = models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.')
    date_joined = models.DateTimeField(auto_now_add=True, help_text='The date and time when the user joined.')
    
    objects = AccManager()

    USERNAME_FIELD = 'username'
    # REQUIRED_FIELDS = ['email']

    def __str__(self):
        return self.username

class SavedHost(models.Model):
    name = models.CharField(max_length=100, default='Session', help_text='Default name of the tab in fronend.')
    user = models.ForeignKey('AccountData', on_delete=models.CASCADE, related_name='saved_hosts', default=None, help_text='The user associated with the saved host.')
    ip = models.GenericIPAddressField(blank=True, null=True, help_text='The IP address of the saved host.')
    hostname = models.CharField(max_length=255, blank=True, null=True, help_text='The hostname of the saved host.')
    port = models.PositiveIntegerField(default=22, blank=True, null=True, help_text='The port number for accessing the saved host.')
    username = models.CharField(max_length=255, blank=True, null=True, help_text='The username for accessing the saved host.')
    password = EncryptedCharField(max_length=500, blank=True, null=True, help_text='The password for accessing the saved host.')

    # Key-related fields
    private_key = models.TextField(blank=True, null=True, help_text='The private key for SSH access (if applicable).')
    # public_key = models.TextField(blank=True, null=True, help_text='The public key for SSH access (if applicable).')
    passphrase = EncryptedCharField(max_length=500, blank=True, null=True, help_text='The passphrase for the private key (if applicable).')

    # Additional fields
    created_at = models.DateTimeField(auto_now_add=True, help_text='The date and time when the saved host was created.')
    updated_at = models.DateTimeField(auto_now=True, help_text='The date and time when the saved host was last updated.')
    color = ColorField(format="hexa",  blank=True, null=True, help_text="Tab color", samples=COLOR_PALETTE)

    def __str__(self):
        if self.hostname is None:
            return "~Config"
        return f"{self.hostname}"
    
# 
#  SESSIONS DATA
# 
class Log(models.Model):
    notedata_logs: 'NotesData'
    sshdata_logs: 'SSHData'

    log_text = models.TextField(help_text='Log entry text.')
    created_at = models.DateTimeField(auto_now_add=True, help_text='The date and time when the log entry was created.')

    def __str__(self):
        return f"Log {self.created_at}: {self.log_text}"


# FIX m
class AbstractModelMeta(ABCMeta, type(models.Model)):...
class BaseData(models.Model, metaclass=AbstractModelMeta):
    log: Log
    create_url: str
    url: str

    name = models.CharField(max_length=100, default='Session', help_text='Default name of the tab in fronend.')
    created_at = models.DateTimeField(auto_now_add=True, help_text='The date and time when the data was created.')
    updated_at = models.DateTimeField(auto_now=True, help_text='The date and time when the data was last updated.')
    
    # Logs related table
    logs = models.ManyToManyField(Log, related_name='%(class)s_logs', blank=True, help_text='Logs related to this data.')

    # User who created the session
    session_master = models.ForeignKey(AccountData, on_delete=models.CASCADE, null=False, blank=False, help_text='The user who created the session.')
    session_lock = models.BooleanField(default=True, help_text='This flags informs if other session users (except master) can iteract with terminal')
    session_open = models.BooleanField(default=False, help_text='This flags informs if other users can join this session')
    sessions = GenericRelation('SessionsList', related_query_name='session')
    session_key = models.CharField(default=None, max_length=500, blank=True, null=True, help_text='This key is use in session sharing')

    class Meta:
        abstract = True  # This makes BaseData an abstract model, preventing database table creation.

    def __str__(self):
        return self.name
    
    def _get_session_count(self, is_active=None):
        content_type = ContentType.objects.get_for_model(self.__class__, for_concrete_model=True)
        queryset = SessionsList.objects.filter(
            object_id=self.pk,
            content_type=content_type,
        )
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        return queryset.count()

    def get_sessions_count(self):
        return self._get_session_count()

    def get_active_sessions_count(self):
        return self._get_session_count(is_active=True)


    def close(self, *args, **kwargs) -> None:
        self.delete()


    @classmethod
    @strip_args('name')
    def open(cls, user, name, session_open, color, *args, **kwargs) -> list[Self, 'SessionsList']:
        data_obj = cls.objects.create(
            session_master=user,
            session_open = session_open,
            name=name,
        )
        data_obj.save()

        if session_open:
           data_obj.setup_sharing()

        session = SessionsList.objects.create(
            name = name,
            user = user,
            content_type=ContentType.objects.get_for_model(cls),
            object_id=data_obj.pk,
            color=color,
        )

        session.save()

        log_entry = Log.objects.create(
            log_text=f"Session created by {user.get_username()} for SSHData: {data_obj.name}",
        )

        log_entry.save()

        data_obj.logs.add(log_entry)

        return data_obj, session

    def setup_sharing(self):
        self.session_open = True
        self.session_key = secrets.token_hex(64)
        self.save()

        return self.session_key

    def stop_sharing(self):
        self.session_open = False
        self.session_key = None
        self.save()

    def update_obj(self, data_dict):
        for key, value in data_dict.items():
            setattr(self, key, value)
        self.save()

    @classmethod
    def get_access_permission(cls):
        try:
            return f'{TerminalConfig.name}.{cls._meta.permissions[0][0]}'
        except Exception as e:
            raise ImproperlyConfigured(f"The Data session model is not set up correctly.: {e}")


class NotesData(BaseData):
    content = models.JSONField(blank=True, null=True, default=None, help_text='All note content for this note session')

    @property
    def create_url(self):
        return reverse('note.create')

    @property
    def url(self):
        return reverse('note.detail', kwargs={'pk': self.pk})
    # logs = GenericRelation(Log, related_query_name='notesdata_logs', blank=True, help_text='Logs related to this notes data.')

    def __str__(self):
        return f"Note: {self.name}"
    
    class Meta:
        permissions = [
            ("USE_NOTE", "This permission give user ability to use notes funcjonality"),
        ]


    def get_content(self):
        return self.content

    def set_content(self, delta):
        self.content = delta
        self.save()

class SSHData(BaseData):
    CACHED_CREDENTIALS = False
    BUFFER_SIZE_LIMIT = 65536
    TERM_MIN_WIDTH, TERM_MIN_HEIGHT = 20, 12

    _buffers = {}

    ip = models.GenericIPAddressField(blank=True, null=True, help_text='The IP address of the host.')
    hostname = models.CharField(max_length=255, blank=True, null=True, help_text='The hostname of the host.')
    port = models.PositiveIntegerField(default=22, blank=True, null=True, help_text='The port number for accessing the host.')
    save_session = models.ForeignKey(SavedHost, on_delete=models.SET_NULL, related_name='sshdate', blank=True, null=True, default=None, help_text='Saved Host data reference')
    content = models.TextField(blank=True, null=False, default='', help_text='All terminal content for this ssh session')

    @property
    def create_url(self):
        return reverse('ssh.create')

    @property
    def url(self):
        return reverse('ssh.detail', kwargs={'pk': self.pk})
    # logs = GenericRelation(Log, related_query_name='sshdata_logs', blank=True, help_text='Logs related to this SSH data.')

    def __str__(self):
        return f"SSH Connection: {self.name}"
    
    def close(self, *args, **kwargs):
        SSHModule.disconnect(self.id)
        super().close()

    async def read(self):
        data = await SSHModule.read(await self.__get_session_id())

        if data is not None and data != '':
            updated_buffer = self.__get_buffer(self.id) + data
            self.__set_buffer(self.id, updated_buffer)

            if len(updated_buffer) >= self.BUFFER_SIZE_LIMIT:
                await self.__update_content(self.id)

        return data

    async def send(self, data):
        try:
            await SSHModule.send(await self.__get_session_id(), data)
        except Exception:
            raise

    @sync_to_async
    def get_save_session(self):
        try:
            return self.save_session
        except ObjectDoesNotExist:
            return None

    async def connect(self, username=None, password=None, private_key=None, passphrase=None):
        await self.check_cache_and_update_flag()

        save_session = await self.get_save_session()
        hostname = self.ip if self.hostname is None else self.hostname
        port = self.port

        if save_session:
            username = save_session.username
            password = save_session.password
            private_key = save_session.private_key
            passphrase = save_session.passphrase
            hostname = save_session.ip if save_session.hostname is None else save_session.hostname
            port = save_session.port
        elif self.CACHED_CREDENTIALS:
            cache_key = f'{await self.__get_session_id()}'
            cache_credentials = cache.get(cache_key)
            username = cache_credentials.get('username')
            password = cache_credentials.get('password')
            private_key = cache_credentials.get('private_key')
            passphrase = cache_credentials.get('passphrase')

        try:
            await SSHModule.connect_or_create_instance(
                await self.__get_session_id(),
                host=hostname,
                username=username,
                password=password,
                pkey=private_key,
                passphrase=passphrase,
                port=port
            )
        except ReconnectRequired as e:
            session_saved = await self.__check_save_session_exists()
            raise ReconnectRequired(message=e, session_saved=session_saved)
        except Exception:
            raise

    async def disconnect(self):
        await self.__flush_buffer()
        session_id = await self.__get_session_id()
        SSHModule.disconnect(session_id)

    async def resize_terminal(self):
        await SSHModule.resize_terminals_in_group(await self.__get_session_id(),
                                                  self.TERM_MIN_WIDTH, self.TERM_MIN_HEIGHT)

    async def set_terminal_size(self, term_width, term_height):
        await SSHModule.add_terminals_in_group(await self.__get_session_id(), term_width, term_height)

    async def del_terminal_size(self, term_width, term_height):
        await SSHModule.del_terminals_in_group(await self.__get_session_id(), term_width, term_height)


    @sync_to_async
    def __get_session_id(self):
        return self.sessions.all().first().object_id

    async def check_cache_and_update_flag(self):
        if cache.get(await self.__get_session_id()) is None:
            self.CACHED_CREDENTIALS = False

    @classmethod
    async def __update_content(cls, instance_id):
        buffer_content = cls.__get_buffer(instance_id)
        if buffer_content:
            instance = await sync_to_async(cls.objects.get)(id=instance_id)
            instance.content += buffer_content
            await sync_to_async(instance.save)()
            cls.__set_buffer(instance_id, '')

    @classmethod
    def __get_buffer(cls, instance_id):
        return cls._buffers.setdefault(instance_id, '')

    @classmethod
    def __set_buffer(cls, instance_id, data):
        cls._buffers[instance_id] = data

    async def get_content(self):
        await self.__flush_buffer()
        return self.content

    async def __flush_buffer(self):
        await self.__update_content(self.id)

    async def __check_save_session_exists(self):
        return bool(self.save_session)

    @classmethod
    def cache_credentials(cls, username, password, private_key, passphrase, cache_key):
        credentials = strip_object(
            {
                'username': username,
                'password': password,
                'private_key': private_key,
                'passphrase': passphrase
            }
        )
        cache.set(cache_key, credentials, timeout=60)
        cls.CACHED_CREDENTIALS = True

    @classmethod
    @strip_args('name', 'hostname', 'username', 'password', 'private_key', 'passphrase', 'port', 'ip')
    def open(cls, user: AccountData, name, hostname, username, password, private_key, passphrase, port, ip, *args, color=COLOR_PALETTE[0], session_open=False, save=False, save_session=None, **kwargs):
        ssh_data, session = super().open(user, name, session_open, color, *args, **kwargs)

        ssh_data.ip=ip
        ssh_data.hostname=hostname
        ssh_data.port=port

        if save:
            SavedHost.objects.create(
                user = user,
                name = name,
                ip = ip,
                hostname = hostname,
                username = username,
                password = password,
                private_key = private_key,
                passphrase = passphrase,
                port = port,
                color = color,
            )

        ssh_data.save_session=save_session

        ssh_data.save()

        cls.cache_credentials(username=username, password=password, private_key=private_key,
                              passphrase=passphrase, cache_key=ssh_data.pk)

        return ssh_data, session
    
    class Meta:
        permissions = [
            ("USE_SSH", "This permission give user ability to use SSH funcjonality"),
        ]

class SessionsList(models.Model):
    name = models.CharField(max_length=100, default='Session', help_text='Name of the tab in fronend.')
    user = models.ForeignKey(AccountData, on_delete=models.CASCADE, related_name='sessions', help_text='The user associated with the session.')
    sharing_enabled = models.BooleanField(default=False, help_text='Flag indicating if sharing is enabled for the session.')
    is_active = models.BooleanField(default=True, help_text='Flag indicating if the session is active.')
    color = ColorField(format="hexa",  blank=True, null=True, help_text="Tab color", samples=COLOR_PALETTE)

    # GenericForeignKey to reference either SSHData or NotesData
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, limit_choices_to={'model__in': ['sshdata', 'notesdata']})
    object_id = models.PositiveIntegerField(null=False)
    content_object = GenericForeignKey('content_type', 'object_id')


    # ssh_data_relation = GenericRelation(SSHData)
    # notes_data_relation = GenericRelation(NotesData)

    class Meta:
        # To session form the same user to Session Data can not exist
        unique_together = ['user', 'content_type', 'object_id']

    def clean(self):
        content_type = self.content_type
        object_id = self.object_id
        
        if content_type and object_id:
            try:
                content_type.get_object_for_this_type(pk=object_id)
            except content_type.model_class().DoesNotExist:
                raise ValidationError(f"The object with id {object_id} does not exist for the specified content type.")
            
        if not object_id:
            raise ValidationError(f"The object id can not be negative.")
        

    def __str__(self):
        return f"{self.user.username}'s session {self.pk}"
    
    @classmethod
    def joinWithOutContext(cls, user, session_key):
        other_session =  SessionsList.get_session_from_key(session_key)
        
        if other_session:
            if not user.has_perm(other_session.content_object.get_access_permission()):
                return None, True

        
            return SessionsList._join(
                user=user,
                data_obj = other_session.content_object,
                name =  other_session.content_object.name,
            )

        return None, False

    @classmethod
    def _join(cls, user, data_obj, name):
        session, created = cls.objects.get_or_create(
            user = user,
            content_type=ContentType.objects.get_for_model(data_obj),
            object_id=data_obj.id
        )

        session.name = name if name else data_obj.name
        session.save()

        return session, created

    def close(self):
        self.delete()
    
    def update_obj(self, data_dict):
        for key, value in data_dict.items():
            setattr(self, key, value)
        self.save()

    @staticmethod
    def get_session_from_key(sesssion_key):
        sessions = SessionsList.objects.all()
        for session in sessions:
            content = session.content_object
            if content.session_open and content.session_key == sesssion_key:
                return session

    def get_session_dict(self, user):
        return {
            'name': self.name,
            'color': self.color,
            'pk': self.pk,
            'object_id': self.object_id,
            'content_type': self.content_object.name,
            'is_master': self.content_object.session_master == user,
            'session_open': self.content_object.session_open,
            'url': self.content_object.url,
            'create_url': self.content_object.create_url,
        }