# Generated by Django 4.2.5 on 2024-01-11 23:51

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('terminal', '0024_notesdata_session_key_sshdata_session_key'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='sessionslist',
            unique_together=set(),
        ),
    ]
