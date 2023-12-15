from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import AccountData, SavedHost, SessionsList, SSHData, NotesData
from django import forms
from django.contrib import admin
from django.forms import CharField, PasswordInput, TextInput

class SavedHostAdminForm(forms.ModelForm):
    password = CharField(widget=PasswordInput(), required=False, help_text='The password for accessing the saved host.')
    passphrase = CharField(widget=PasswordInput(), required=False,  help_text='The passphrase for the private key (if applicable).')
    private_key = CharField(widget=PasswordInput(), required=False,  help_text='The private key for SSH access (if applicable).')

class SavedHostsAdmin(admin.ModelAdmin):
    form = SavedHostAdminForm
    list_display = ('hostname', 'ip_address_v4', 'ip_address_v6', 'username', 'user', 'created_at', 'updated_at')
    search_fields = ('hostname', 'ip_address_v4', 'ip_address_v6', 'username', 'user__username')

admin.site.register(SavedHost, SavedHostsAdmin)



class SavedHostsInline(admin.TabularInline):
    model = SavedHost
    extra = 1

class UserAdmin(BaseUserAdmin):
    inlines = [SavedHostsInline]

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )


admin.site.register(AccountData, UserAdmin)


class SessionsListAdmin(admin.ModelAdmin):
    list_display = ('user', 'content_type', 'object_id', 'get_object_name', 'sharing_enabled', 'is_active')
    search_fields = ['user__username']

    def get_object_name(self, obj):
        # Access the related object's name
        return obj.content_object.name if obj.content_object else None
    get_object_name.short_description = 'Object Name'

admin.site.register(SessionsList, SessionsListAdmin)