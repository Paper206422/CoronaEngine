#pragma once

#include <cef_browser.h>
#include <wrapper/cef_message_router.h>

namespace Corona::Systems::UI {

bool handle_realtime_process_message(const CefRefPtr<CefProcessMessage>& message);

bool forward_process_message_to_router(const CefRefPtr<CefMessageRouterBrowserSide>& browser_side_router,
                                       CefRefPtr<CefBrowser> browser,
                                       CefRefPtr<CefFrame> frame,
                                       CefProcessId source_process,
                                       CefRefPtr<CefProcessMessage> message);

}  // namespace Corona::Systems::UI