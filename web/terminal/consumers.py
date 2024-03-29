import asyncio
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.exceptions import ObjectDoesNotExist
from terminal.models import SessionsList, BaseData
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async
from terminal.errors import ReconnectRequired

class SessionCosumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = None
        self.ssh_session_id = None
        self.read_task = None

    @database_sync_to_async
    def __get_session(self):
        try:
            obj: SessionsList = SessionsList.objects.select_related('user', 'content_type').get(pk=self.session_id) # slave
            data_obj: BaseData = obj.content_object # master
        except ObjectDoesNotExist:
            return None, None

        return obj, data_obj

    async def connect(self, *args, **kwargs):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        obj, data_obj = await self.__get_session()
        self.ssh_session_id = str(data_obj.id)
        await self.channel_layer.group_add(self.ssh_session_id, self.channel_name)
        await self.accept()

        if obj is None or data_obj is None:
            return

        if obj.content_type.model == 'sshdata':
            await self.send_group_message(msg_type='action', message={'type': 'load_content',
                                                                                'data': await data_obj.get_content()})
            try:
                await data_obj.connect()
            except ReconnectRequired as e:
                await self.send_group_message(e)
                await self.send_group_message(msg_type='action', message={'type': 'require_reconnect',
                                                                                'session_saved': e.session_saved})
            except Exception as e:
                await self.send_group_message(e)

            self.start_read()

        elif obj.content_type.model == 'notesdata':
            data = await sync_to_async(lambda: data_obj.get_content())()
            await self.send_group_message(msg_type='action', myself=True, message={'type': 'load_content', 'delta': data})

    async def disconnect(self, code):
        obj, data_obj = await self.__get_session()

        if obj is None or data_obj is None:
            return

        if obj.content_type.model == 'sshdata':
            await data_obj.disconnect()

    async def send_group_message(self, message, exclusive=False, myself=False, msg_type=None):
        if msg_type is not None:
            message = {'type': msg_type, 'content': message}
        elif isinstance(message, Exception):
            message = {'type': 'error', 'content': str(message)}
        else:
            message = {'type': 'info', 'content': message}

        await self.channel_layer.group_send(
            self.ssh_session_id,
            {
                'type': 'group_message',
                'message': message,
                'to_myself': myself,
                'exclusive': exclusive,
                'sender_channel_name': self.channel_name
            }
        )

    async def group_message(self, event):
        if event.get('to_myself') is True and event.get('sender_channel_name') == self.channel_name and \
                event.get('sender_channel_name') is not None:
            await self.send(text_data=json.dumps({'message': event['message']}))
            return

        elif event.get('exclusive') is True:
            if event.get('sender_channel_name') != self.channel_name and event.get('sender_channel_name') is not None:
                await self.send(text_data=json.dumps({'message': event['message']}))
                return
            else:
                return

        await self.send(text_data=json.dumps({'message': event['message']}))

    async def receive(self, text_data=None, bytes_data=None):
        message = json.loads(text_data)
        obj, data_obj = await self.__get_session()

        if obj is None or data_obj is None:
            return

        if obj.content_type.model == 'sshdata':
            match message.get('action'):
                case 'execute':
                    data = message.get('data')
                    if data:

                        try:
                            await data_obj.send(data)
                        except Exception as e:
                            await self.send_group_message(e)
                        self.start_read()

                case 'reconnect':
                    if message.get('type') == 'form':
                        data = message.get('data')
                        data = {k: str(v).strip() if v else None for k, v in data.items()}
                        await sync_to_async(
                            lambda: data_obj.cache_credentials(
                                cache_key=data_obj.id,
                                username=data.get('username'),
                                password=data.get('password'),
                                private_key=data.get('private_key'),
                                passphrase=data.get('passphrase')
                            )
                        )()

                    try:
                        await data_obj.connect()
                    except ReconnectRequired as e:
                        await self.send_group_message(e)
                        await self.send_group_message(msg_type='action', message={'type': 'require_reconnect',
                                                                                  'session_saved': e.session_saved})
                    except Exception as e:
                        await self.send_group_message(e)

                    await self.send_group_message(msg_type='action', message={'type': 'reconnect_successful'})
                    self.start_read()

                case 'resize':
                    if message.get('type') == 'del':
                        size = message.get('data')
                        await data_obj.del_terminal_size(size.get('cols'), size.get('rows'))

                    elif message.get('type') == 'new':
                        size = message.get('data')
                        await data_obj.set_terminal_size(size.get('cols'), size.get('rows'))
                        await data_obj.resize_terminal()

        elif obj.content_type.model == 'notesdata':
            match message.get('action'):
                case 'insert':
                    data = message.get('data')
                    text = data.get('text')
                    index = data.get('index')
                    await self.send_group_message(msg_type='action', exclusive=True,
                                                  message={'type': 'insert', 'text': text, 'index': index})

                case 'delete':
                    data = message.get('data')
                    length = data.get('length')
                    index = data.get('index')
                    await self.send_group_message(msg_type='action', exclusive=True,
                                                  message={'type': 'delete', 'length': length, 'index': index})

                case 'format-change':
                    data = message.get('data')
                    format_type = data.get('format_type')
                    value = data.get('value')
                    index = data.get('index')
                    length = data.get('length')
                    await self.send_group_message(msg_type='action', exclusive=True,
                                                  message={'type': 'format-change', 'format_type': format_type,
                                                           'value': value, 'index': index, 'length': length})

                case 'update_content':
                    data = message.get('data')
                    await sync_to_async(lambda: data_obj.set_content(data.get('delta')))()





    def start_read(self):
        if self.read_task is None or self.read_task.done():
            self.read_task = asyncio.create_task(self.read())

    async def read(self):
        no_data_duration = 0

        while True:
            if no_data_duration >= 30:
                return

            obj, data_obj = await self.__get_session()

            if obj is None or data_obj is None:
                return

            if obj.content_type.model == 'sshdata':
                data = await data_obj.read()
            if data is not None:
                no_data_duration = 0
                await self.send_group_message(data)
            else:
                no_data_duration += 0.1

            await asyncio.sleep(0.1)
