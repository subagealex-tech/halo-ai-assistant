from typing import Optional


class ListNode:
    def __init__(self, val: int = 0, next: Optional["ListNode"] = None):
        self.val = val
        self.next = next


def reverse_list(head: Optional[ListNode]) -> Optional[ListNode]:
    """Reverse a singly linked list iteratively."""
    prev = None
    current = head

    while current:
        next_temp = current.next  # store next node
        current.next = prev       # reverse the pointer
        prev = current            # advance prev
        current = next_temp       # advance current

    return prev  # prev is the new head


# --- Helper utilities for testing ---

def build_list(values: list[int]) -> Optional[ListNode]:
    dummy = ListNode()
    current = dummy
    for v in values:
        current.next = ListNode(v)
        current = current.next
    return dummy.next


def to_list(head: Optional[ListNode]) -> list[int]:
    result = []
    while head:
        result.append(head.val)
        head = head.next
    return result


if __name__ == "__main__":
    head = build_list([1, 2, 3, 4, 5])
    reversed_head = reverse_list(head)
    print(to_list(reversed_head))  # [5, 4, 3, 2, 1]

    print(to_list(reverse_list(None)))       # []
    print(to_list(reverse_list(build_list([1]))))  # [1]
