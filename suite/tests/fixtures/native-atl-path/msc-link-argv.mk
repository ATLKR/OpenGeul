	unset INCLUDE && \
	$(gb_LINK) \
		$(if $(filter Library CppunitTest,$(TARGETTYPE)),$(gb_Library_TARGETTYPEFLAGS)) \
		$(if $(filter StaticLibrary,$(TARGETTYPE)),-LIB) \
		-nologo \
		$(if $(filter Executable,$(TARGETTYPE)),$(gb_Executable_TARGETTYPEFLAGS)) \
		$(if $(T_SYMBOLS),$(if $(filter Executable Library CppunitTest,$(TARGETTYPE)),$(call gb_Windows_PE_TARGETTYPEFLAGS_DEBUGINFO,$(DEFS))),) \
		$(if $(filter YES,$(TARGETGUI)), -SUBSYSTEM:WINDOWS$(gb_MSC_SUBSYSTEM_VERSION), -SUBSYSTEM:CONSOLE$(gb_MSC_SUBSYSTEM_VERSION)) \
		$(if $(filter YES,$(LIBRARY_X64)), -MACHINE:X64) \
		$(if $(filter YES,$(PE_X86)), -MACHINE:X86) \
		$(if $(filter YES,$(LIBRARY_X64)), \
			-LIBPATH:$(COMPATH)/lib/x64 \
			-LIBPATH:$(WINDOWS_SDK_HOME)/lib/x64 \
			-LIBPATH:$(UCRTSDKDIR)lib/$(UCRTVERSION)/ucrt/x64 \
		    $(if $(filter 80 81 10,$(WINDOWS_SDK_VERSION)),-LIBPATH:$(WINDOWS_SDK_HOME)/lib/$(WINDOWS_SDK_LIB_SUBDIR)/um/x64)) \
		$(if $(filter YES,$(PE_X86)), \
			-LIBPATH:$(COMPATH)/lib/x86 \
			-LIBPATH:$(WINDOWS_SDK_HOME)/lib/x86 \
			-LIBPATH:$(UCRTSDKDIR)lib/$(UCRTVERSION)/ucrt/x86 \
			$(if $(filter 80 81 10,$(WINDOWS_SDK_VERSION)),-LIBPATH:$(WINDOWS_SDK_HOME)/lib/$(WINDOWS_SDK_LIB_SUBDIR)/um/x86)) \
		$(T_USE_LD) $(T_LDFLAGS) \
		$(if $(filter Library CppunitTest Executable,$(TARGETTYPE)),/NATVIS:$(SRCDIR)/solenv/vs/LibreOffice.natvis) \
		@$${RESPONSEFILE} \
		$(foreach lib,$(sort $(LINKED_LIBS)),$(call gb_Library_get_ilibfilename,$(lib))) \
		$(foreach lib,$(sort $(LINKED_STATIC_LIBS)),$(call gb_StaticLibrary_get_filename,$(lib))) \
		$(if $(filter-out StaticLibrary,$(TARGETTYPE)),\
			$(sort $(T_LIBS)) user32.lib \
			-manifestfile:$(WORKDIR)/LinkTarget/$(2).manifest \
			-pdb:$(call gb_LinkTarget__get_pdb_filename,$(WORKDIR)/LinkTarget/$(2))) \
		$(if $(ILIBTARGET),-out:$(1) -implib:$(ILIBTARGET),-out:$(1)) \
