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
winaccessibility_native_atl_INCLUDE := $(foreach i,$(ATL_INCLUDE), -I$(i))
ifeq ($(OS)_$(CPUNAME)_$(COM),WNT_AARCH64_MSC)
ifneq ($(filter %-cygwin,$(MAKE_HOST)),)
ifeq ($(strip $(ATL_INCLUDE)),)
$(error ATL include path is empty)
endif
winaccessibility_native_atl_shquote = '$(subst ','"'"',$(1))'
define winaccessibility_native_atl_path
$(if $(strip $(1)),,$(error ATL path is empty))$(eval winaccessibility_native_atl_converted := $(shell cygpath -lm $(call winaccessibility_native_atl_shquote,$(1))))$(if $(filter 0,$(.SHELLSTATUS)),,$(error ATL path conversion failed))$(if $(strip $(winaccessibility_native_atl_converted)),,$(error ATL path conversion returned no path))"$(winaccessibility_native_atl_converted)"
endef
winaccessibility_native_atl_INCLUDE := $(foreach i,$(ATL_INCLUDE), -I$(call winaccessibility_native_atl_path,$(i)))
endif
endif

$(eval $(call gb_Library_Library,winaccessibility))

$(eval $(call gb_Library_use_custom_headers,winaccessibility,winaccessibility/ia2/idl))

$(eval $(call gb_Library_set_include,winaccessibility,\
	$$(INCLUDE) \
	-I$(SRCDIR)/winaccessibility/inc \
	$(winaccessibility_native_atl_INCLUDE) \
))

$(eval $(call gb_Library_use_sdk_api,winaccessibility))

$(eval $(call gb_Library_set_componentfile,winaccessibility,winaccessibility/source/service/winaccessibility,services))

$(eval $(call gb_Library_use_common_precompiled_header,winaccessibility))

$(eval $(call gb_Library_add_exception_objects,winaccessibility,\
	winaccessibility/source/service/AccObject \
	winaccessibility/source/service/ResIDGenerator \
	winaccessibility/source/service/AccObjectWinManager \
	winaccessibility/source/service/AccEventListener \
	winaccessibility/source/service/AccComponentEventListener \
	winaccessibility/source/service/AccContainerEventListener \
	winaccessibility/source/service/AccDialogEventListener \
	winaccessibility/source/service/AccFrameEventListener \
	winaccessibility/source/service/AccWindowEventListener \
	winaccessibility/source/service/AccMenuEventListener \
	winaccessibility/source/service/AccTextComponentEventListener \
	winaccessibility/source/service/AccObjectContainerEventListener \
	winaccessibility/source/service/AccParagraphEventListener \
	winaccessibility/source/service/AccDescendantManagerEventListener \
	winaccessibility/source/service/AccListEventListener \
	winaccessibility/source/service/AccTableEventListener \
	winaccessibility/source/service/AccTreeEventListener \
	winaccessibility/source/service/AccTopWindowListener \
	winaccessibility/source/service/msaaservice_impl \
))

$(eval $(call gb_Library_use_externals,winaccessibility,\
	boost_headers \
))

$(eval $(call gb_Library_use_libraries,winaccessibility,\
	UAccCOM \
	comphelper \
	cppu \
	cppuhelper \
	vcl \
	sal \
	tk \
	tl \
))

$(eval $(call gb_Library_use_system_win32_libs,winaccessibility,\
	oleacc \
	advapi32 \
	delayimp \
	kernel32 \
	ole32 \
	oleaut32 \
	shlwapi \
	user32 \
	uuid \
	gdi32 \
	shell32 \
	imm32 \
	winspool \
))

# vim:set noet sw=4 ts=4:
