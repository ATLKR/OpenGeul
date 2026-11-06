#pragma once
#include <cstdint>
// Compile-only synthetic constants; FOCUSED and MSAA focus bit fixed.
namespace AccessibleStateType {
inline constexpr std::int64_t ARMED=std::int64_t(1)<<0;
inline constexpr std::int64_t BUSY=std::int64_t(1)<<1;
inline constexpr std::int64_t CHECKED=std::int64_t(1)<<2;
inline constexpr std::int64_t COLLAPSE=std::int64_t(1)<<3;
inline constexpr std::int64_t DEFAULT=std::int64_t(1)<<4;
inline constexpr std::int64_t DEFUNC=std::int64_t(1)<<5;
inline constexpr std::int64_t EDITABLE=std::int64_t(1)<<6;
inline constexpr std::int64_t EXPANDABLE=std::int64_t(1)<<7;
inline constexpr std::int64_t EXPANDED=std::int64_t(1)<<8;
inline constexpr std::int64_t FOCUSABLE=std::int64_t(1)<<9;
inline constexpr std::int64_t FOCUSED=std::int64_t(1)<<10;
inline constexpr std::int64_t INDETERMINATE=std::int64_t(1)<<11;
inline constexpr std::int64_t MOVEABLE=std::int64_t(1)<<12;
inline constexpr std::int64_t MULTI_SELECTABLE=std::int64_t(1)<<13;
inline constexpr std::int64_t OFFSCREEN=std::int64_t(1)<<14;
inline constexpr std::int64_t PRESSED=std::int64_t(1)<<15;
inline constexpr std::int64_t RESIZABLE=std::int64_t(1)<<16;
inline constexpr std::int64_t SELECTABLE=std::int64_t(1)<<17;
inline constexpr std::int64_t SELECTED=std::int64_t(1)<<18;
inline constexpr std::int64_t SHOWING=std::int64_t(1)<<19;
inline constexpr std::int64_t VISIBLE=std::int64_t(1)<<20;
}
namespace AccessibleRole {
inline constexpr short BUTTON_DROPDOWN=100;
inline constexpr short CHECK_MENU_ITEM=101;
inline constexpr short MENU=102;
inline constexpr short MENU_ITEM=103;
inline constexpr short PUSH_BUTTON=104;
inline constexpr short RADIO_MENU_ITEM=105;
inline constexpr short TOGGLE_BUTTON=106;
inline constexpr short TOOL_BAR=107;
}
inline constexpr std::uint32_t STATE_SYSTEM_BUSY=std::uint32_t(1)<<0;
inline constexpr std::uint32_t STATE_SYSTEM_CHECKED=std::uint32_t(1)<<1;
inline constexpr std::uint32_t STATE_SYSTEM_COLLAPSED=std::uint32_t(1)<<3;
inline constexpr std::uint32_t STATE_SYSTEM_DEFAULT=std::uint32_t(1)<<4;
inline constexpr std::uint32_t STATE_SYSTEM_EXPANDED=std::uint32_t(1)<<5;
inline constexpr std::uint32_t STATE_SYSTEM_FOCUSABLE=std::uint32_t(1)<<6;
inline constexpr std::uint32_t STATE_SYSTEM_FOCUSED=std::uint32_t(1)<<2;
inline constexpr std::uint32_t STATE_SYSTEM_HASPOPUP=std::uint32_t(1)<<7;
inline constexpr std::uint32_t STATE_SYSTEM_INVISIBLE=std::uint32_t(1)<<8;
inline constexpr std::uint32_t STATE_SYSTEM_MIXED=std::uint32_t(1)<<9;
inline constexpr std::uint32_t STATE_SYSTEM_MOVEABLE=std::uint32_t(1)<<10;
inline constexpr std::uint32_t STATE_SYSTEM_MULTISELECTABLE=std::uint32_t(1)<<11;
inline constexpr std::uint32_t STATE_SYSTEM_OFFSCREEN=std::uint32_t(1)<<12;
inline constexpr std::uint32_t STATE_SYSTEM_PRESSED=std::uint32_t(1)<<13;
inline constexpr std::uint32_t STATE_SYSTEM_PROTECTED=std::uint32_t(1)<<14;
inline constexpr std::uint32_t STATE_SYSTEM_READONLY=std::uint32_t(1)<<15;
inline constexpr std::uint32_t STATE_SYSTEM_SELECTABLE=std::uint32_t(1)<<16;
inline constexpr std::uint32_t STATE_SYSTEM_SELECTED=std::uint32_t(1)<<17;
inline constexpr std::uint32_t STATE_SYSTEM_SIZEABLE=std::uint32_t(1)<<18;
inline constexpr std::uint32_t STATE_SYSTEM_UNAVAILABLE=std::uint32_t(1)<<19;
