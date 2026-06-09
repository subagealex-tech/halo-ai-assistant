def merge_sorted_arrays(arr1: list[int], arr2: list[int]) -> list[int]:
    """
    Merge two sorted arrays into a single sorted array.
    
    Uses two-pointer technique for O(n + m) time and O(n + m) space.
    """
    merged = []
    i, j = 0, 0

    # Compare elements from both arrays and append the smaller one
    while i < len(arr1) and j < len(arr2):
        if arr1[i] <= arr2[j]:
            merged.append(arr1[i])
            i += 1
        else:
            merged.append(arr2[j])
            j += 1

    # Append any remaining elements
    merged.extend(arr1[i:])
    merged.extend(arr2[j:])

    return merged


def main():
    # Test cases
    test_cases = [
        ([1, 3, 5, 7], [2, 4, 6, 8]),
        ([1, 2, 3], [4, 5, 6]),
        ([1, 5, 9], [2, 3, 6, 7, 10]),
        ([], [1, 2, 3]),
        ([], []),
        ([2, 2, 2], [2, 2]),
    ]

    for arr1, arr2 in test_cases:
        result = merge_sorted_arrays(arr1, arr2)
        print(f"{str(arr1):>20} + {str(arr2):<20} => {result}")


if __name__ == "__main__":
    main()
