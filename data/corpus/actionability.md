# Auto-waiting

## Introduction

Playwright performs a range of actionability checks on the elements before making actions to ensure these actions
behave as expected. It auto-waits for all the relevant checks to pass and only then performs the requested action. If the required checks do not pass within the given `timeout`, action fails with the `TimeoutError`.

For example, for `locator.click`, Playwright will ensure that:
- locator resolves to exactly one element
- element is [Visible]
- element is [Stable], as in not animating or completed animation
- element [Receives Events], as in not obscured by other elements
- element is [Enabled]
- element is [Not Inert]

Here is the complete list of actionability checks performed for each action:

| Action | [Visible] | [Stable] | [Receives Events] | [Enabled] | [Editable] | [Not Inert] |
| :- | :-: | :-: | :-: | :-: | :-: | :-: |
| `locator.check` | Yes | Yes | Yes | Yes | - | Yes |
| `locator.click` | Yes | Yes | Yes | Yes | - | Yes |
| `locator.dblclick` | Yes | Yes | Yes | Yes | - | Yes |
| `locator.set_checked` | Yes | Yes | Yes | Yes | - | Yes |
| `locator.tap` | Yes | Yes | Yes | Yes | - | Yes |
| `locator.uncheck` | Yes | Yes | Yes | Yes | - | Yes |
| `locator.hover` | Yes | Yes | Yes | - | - | - |
| `locator.drag_to` | Yes | Yes | Yes | - | - | - |
| `locator.screenshot` | Yes | Yes | - | - | - | - |
| `locator.fill` | Yes | - | - | Yes | Yes | Yes |
| `locator.clear` | Yes | - | - | Yes | Yes | Yes |
| `locator.select_option` | Yes | - | - | Yes | - | Yes |
| `locator.select_text` | Yes | - | - | - | - | - |
| `locator.scroll_into_view_if_needed` | - | Yes | - | - | - | - |
| `locator.blur` | - | - | - | - | - | - |
| `locator.dispatch_event` | - | - | - | - | - | - |
| `locator.focus` | - | - | - | - | - | - |
| `locator.press` | - | - | - | - | - | - |
| `locator.press_sequentially` | - | - | - | - | - | - |
| `locator.set_input_files` | - | - | - | - | - | - |

## Forcing actions

Some actions like `locator.click` support `force` option that disables non-essential actionability checks,
for example passing truthy `force` to `locator.click` method will not check that the target element actually
receives click events.

## Assertions

Playwright includes auto-retrying assertions that remove flakiness by waiting until the condition is met, similarly to auto-waiting before actions.

| Assertion | Description |
| :- | :- |
| `locator_assertions.to_be_attached` | Element is attached |
| `locator_assertions.to_be_checked` | Checkbox is checked |
| `locator_assertions.to_be_disabled` | Element is disabled |
| `locator_assertions.to_be_editable` | Element is editable |
| `locator_assertions.to_be_empty` | Container is empty |
| `locator_assertions.to_be_enabled` | Element is enabled |
| `locator_assertions.to_be_focused` | Element is focused |
| `locator_assertions.to_be_hidden` | Element is not visible |
| `locator_assertions.to_be_in_viewport` | Element intersects viewport |
| `locator_assertions.to_be_visible` | Element is visible |
| `locator_assertions.to_contain_text` | Element contains text |
| `locator_assertions.to_have_attribute` | Element has a DOM attribute |
| `locator_assertions.to_have_class` | Element has a class property |
| `locator_assertions.to_have_count` | List has exact number of children |
| `locator_assertions.to_have_c_s_s` | Element has CSS property |
| `locator_assertions.to_have_id` | Element has an ID |
| `locator_assertions.to_have_j_s_property` | Element has a JavaScript property |
| `locator_assertions.to_have_text` | Element matches text |
| `locator_assertions.to_have_value` | Input has a value |
| `locator_assertions.to_have_values` | Select has options selected |
| `page_assertions.to_have_title` | Page has a title |
| `page_assertions.to_have_u_r_l` | Page has a URL |
| `a_p_i_response_assertions.to_be_o_k` | Response has an OK status |

Learn more in the assertions guide.

## Visible

Element is considered visible when it has non-empty bounding box and does not have `visibility:hidden` computed style.

Note that according to this definition:
* Elements of zero size **are not** considered visible.
* Elements with `display:none` **are not** considered visible.
* Elements with `opacity:0` **are** considered visible.

## Stable

Element is considered stable when it has maintained the same bounding box for at least two consecutive animation frames.

## Enabled

Element is considered enabled when it is **not disabled**.

Element is **disabled** when:
- it is a `<button>`, `<select>`, `<input>`, `<textarea>`, `<option>` or `<optgroup>` with a `[disabled]` attribute;
- it is a `<button>`, `<select>`, `<input>`, `<textarea>`, `<option>` or `<optgroup>` that is a part of a `<fieldset>` with a `[disabled]` attribute;
- it is a descendant of an element with `[aria-disabled=true]` attribute.

## Editable

Element is considered editable when it is [enabled] and is **not readonly**.

Element is **readonly** when:
- it is a `<select>`, `<input>` or `<textarea>` with a `[readonly]` attribute;
- it has an `[aria-readonly=true]` attribute and an aria role that [supports it](https://w3c.github.io/aria/#aria-readonly).

## Not Inert

Element is considered not inert when it is **not** a part of an inert subtree. Inert elements cannot be focused, clicked or otherwise interacted with.

Element is **inert** when:
- it is an element with the [`inert`](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Global_attributes/inert) attribute, or a descendant of such an element.

## Receives Events

Element is considered receiving pointer events when it is the hit target of the pointer event at the action point. For example, when clicking at the point `(10;10)`, Playwright checks whether some other element (usually an overlay) will instead capture the click at `(10;10)`.

For example, consider a scenario where Playwright will click `Sign Up` button regardless of when the `locator.click` call was made:
- page is checking that user name is unique and `Sign Up` button is disabled;
- after checking with the server, the disabled `Sign Up` button is replaced with another one that is now enabled.

[Visible]: #visible "Visible"
[Stable]: #stable "Stable"
[Enabled]: #enabled "Enabled"
[Editable]: #editable "Editable"
[Receives Events]: #receives-events "Receives Events"
[Not Inert]: #not-inert "Not Inert"
