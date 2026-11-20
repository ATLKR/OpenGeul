# -*- Mode: makefile-gmake; tab-width: 4; indent-tabs-mode: t -*-
#
#
# This file is part of the LibreOffice project.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
#

# OpenGeul: keep native ATL arguments local to this recipe.
uacccom_native_atl_INCLUDE := $(foreach i,$(ATL_INCLUDE), -I$(i))
uacccom_native_atl_LIB := $(ATL_LIB)
uacccom_native_atl_LIBS := $(ATL_LIB)/atls.lib
uacccom_native_atl_LINK_LIB :=
ifeq ($(OS)_$(CPUNAME)_$(COM),WNT_AARCH64_MSC)
ifneq ($(filter %-cygwin,$(MAKE_HOST)),)
ifeq ($(strip $(ATL_INCLUDE)),)
$(error ATL include path is empty)
endif
uacccom_native_atl_shquote = '$(subst ','"'"',$(1))'
define uacccom_native_atl_path
$(if $(strip $(1)),,$(error ATL path is empty))$(eval uacccom_native_atl_converted := $(shell cygpath -lm $(call uacccom_native_atl_shquote,$(1))))$(if $(filter 0,$(.SHELLSTATUS)),,$(error ATL path conversion failed))$(if $(strip $(uacccom_native_atl_converted)),,$(error ATL path conversion returned no path))"$(uacccom_native_atl_converted)"
endef
uacccom_native_atl_INCLUDE := $(foreach i,$(ATL_INCLUDE), -I$(call uacccom_native_atl_path,$(i)))
uacccom_native_atl_LIB := $(call uacccom_native_atl_path,$(ATL_LIB))
# Native paths with spaces must bypass the sorted T_LIBS word list.
uacccom_native_atl_LINK_LIB := $(uacccom_native_atl_LIB)/atls.lib
uacccom_native_atl_LIBS :=
endif
endif

$(eval $(call gb_Library_Library,UAccCOM))

$(eval $(call gb_Library_use_custom_headers,UAccCOM,winaccessibility/ia2/idl))

$(eval $(call gb_Library_set_include,UAccCOM,\
	$$(INCLUDE) \
	-I$(SRCDIR)/winaccessibility/inc \
	$(uacccom_native_atl_INCLUDE) \
))

$(eval $(call gb_Library_add_defs,UAccCOM,\
	-DUACCCOM_DLLIMPLEMENTATION \
))

$(eval $(call gb_Library_use_sdk_api,UAccCOM))

$(eval $(call gb_Library_add_nativeres,UAccCOM,UAccCOM))

$(eval $(call gb_Library_add_exception_objects,UAccCOM,\
	winaccessibility/source/UAccCOM/AccAction \
	winaccessibility/source/UAccCOM/AccActionBase \
	winaccessibility/source/UAccCOM/AccComponent \
	winaccessibility/source/UAccCOM/AccEditableText \
	winaccessibility/source/UAccCOM/AccHyperLink \
	winaccessibility/source/UAccCOM/AccHypertext \
	winaccessibility/source/UAccCOM/AccImage \
	winaccessibility/source/UAccCOM/AccRelation \
	winaccessibility/source/UAccCOM/AccTable \
	winaccessibility/source/UAccCOM/AccTableCell \
	winaccessibility/source/UAccCOM/AccText \
	winaccessibility/source/UAccCOM/AccTextBase \
	winaccessibility/source/UAccCOM/AccValue \
	winaccessibility/source/UAccCOM/EnumVariant \
	winaccessibility/source/UAccCOM/MAccessible \
	winaccessibility/source/UAccCOM/StdAfx \
	winaccessibility/source/UAccCOM/UAccCOM \
	winaccessibility/source/UAccCOM/UNOXWrapper \
))

$(eval $(call gb_Library_add_ldflags,UAccCOM,\
	/DEF:$(SRCDIR)/winaccessibility/source/UAccCOM/UAccCOM.def $(uacccom_native_atl_LINK_LIB) \
))

$(eval $(call gb_Library_use_libraries,UAccCOM,\
	vcl \
	comphelper \
	cppu \
	sal \
	utl \
))

$(eval $(call gb_Library_use_externals,UAccCOM,\
	boost_headers \
))

$(eval $(call gb_Library_use_system_win32_libs,UAccCOM,\
	oleacc \
	advapi32 \
	delayimp \
	kernel32 \
	ole32 \
	oleaut32 \
	shlwapi \
	user32 \
	uuid \
))

$(eval $(call gb_Library_add_libs,UAccCOM,\
	$(uacccom_native_atl_LIBS) \
))

# vim:set noet sw=4 ts=4:
