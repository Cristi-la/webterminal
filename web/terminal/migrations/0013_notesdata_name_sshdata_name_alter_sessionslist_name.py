# Generated by Django 4.2.5 on 2023-12-28 22:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('terminal', '0012_remove_notesdata_name_remove_sshdata_name_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='notesdata',
            name='name',
            field=models.CharField(default='Session', help_text='Default name of the tab in fronend.', max_length=100),
        ),
        migrations.AddField(
            model_name='sshdata',
            name='name',
            field=models.CharField(default='Session', help_text='Default name of the tab in fronend.', max_length=100),
        ),
        migrations.AlterField(
            model_name='sessionslist',
            name='name',
            field=models.CharField(default='Session', help_text='Name of the tab in fronend.', max_length=100),
        ),
    ]