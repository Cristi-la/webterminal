# Generated by Django 4.2.5 on 2024-01-11 19:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('terminal', '0022_alter_savedhost_color_alter_sessionslist_color'),
    ]

    operations = [
        migrations.AddField(
            model_name='sshdata',
            name='content',
            field=models.TextField(blank=True, default='', help_text='All terminal content for this ssh session'),
        ),
    ]
